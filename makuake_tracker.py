import streamlit as st
import pandas as pd
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
import os
import base64  # 用于数据库下载接口
import requests  # 用于从GitHub恢复备份

# ================= 核心配置 =================
DB_FILE = "makuake.db"
GITHUB_REPO = "Yuuto0331/Yuuto---Makuake-Radar-1.0"  # 你的仓库地址
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # 私有仓库需配置，公开仓库留空

# ================= 自动恢复备份函数 =================
def auto_restore_from_github():
    """启动时自动检查并恢复GitHub备份"""
    # 检查数据库是否健康
    def is_db_healthy():
        if not os.path.exists(DB_FILE):
            return False
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.execute("SELECT 1 FROM projects LIMIT 1")
            conn.close()
            return True
        except Exception as e:
            st.warning(f"数据库损坏: {str(e)}")
            return False

    # 数据库正常则跳过恢复
    if is_db_healthy():
        return

    st.toast("⚠️ 检测到数据库丢失/损坏，正在从GitHub恢复...", icon="⚠️")
    try:
        # 1. 获取backups文件夹下的所有备份目录
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/backups"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        
        res = requests.get(url, headers=headers, timeout=30)
        res.raise_for_status()
        backups = res.json()

        # 筛选出备份目录并按时间排序（最新的在前）
        backup_dirs = [b for b in backups if b["type"] == "dir"]
        if not backup_dirs:
            st.error("❌ GitHub仓库中未找到备份文件夹！")
            return
        latest_dir = sorted(backup_dirs, key=lambda x: x["name"], reverse=True)[0]

        # 2. 获取最新备份目录下的数据库文件
        files_res = requests.get(latest_dir["url"], headers=headers, timeout=30)
        files_res.raise_for_status()
        db_files = [f for f in files_res.json() if f["name"].startswith("makuake_full_") and f["name"].endswith(".db")]
        
        if not db_files:
            st.error("❌ 最新备份中未找到完整数据库文件！")
            return

        # 3. 下载并恢复数据库
        db_url = db_files[0]["download_url"]
        db_data = requests.get(db_url, headers=headers, timeout=30).content
        with open(DB_FILE, "wb") as f:
            f.write(db_data)

        st.success("✅ 数据库恢复成功！所有数据已找回", icon="✅")
    except Exception as e:
        st.error(f"❌ 备份恢复失败：{str(e)}", icon="❌")

# ================= 初始化数据库 =================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 创建项目表
    c.execute('''CREATE TABLE IF NOT EXISTS projects 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  url TEXT UNIQUE, 
                  title TEXT, 
                  interval INTEGER)''')
    
    # 创建历史数据表
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  project_id INTEGER, 
                  amount INTEGER, 
                  supporters INTEGER, 
                  collected_at TIMESTAMP, 
                  FOREIGN KEY(project_id) REFERENCES projects(id))''')
    
    # 创建设置表
    c.execute('''CREATE TABLE IF NOT EXISTS settings 
                 (id INTEGER PRIMARY KEY CHECK (id = 1), 
                  auto_running INTEGER, 
                  interval_seconds INTEGER)''')
    
    # 初始化设置（仅首次）
    c.execute("INSERT OR IGNORE INTO settings (id, auto_running, interval_seconds) VALUES (1, 0, 3600)")
    conn.commit()
    return conn

# 初始化数据库连接
conn = init_db()

# 启动时自动恢复备份
auto_restore_from_github()

# ================= Selenium 数据采集函数 =================
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def get_makuake_data(project_url):
    """采集Makuake项目的当前金额和支持者数"""
    try:
        if not project_url:
            return None, None, "URL不能为空"
        if not project_url.endswith("/"):
            project_url = project_url + "/"

        # Chrome浏览器配置
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")  # 无头模式
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
        options.add_argument("--lang=ja-JP")

        # 启动浏览器
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager(driver_version="145.0.7632.116").install()),
            options=options
        )
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # 访问页面
        driver.get(project_url)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(3)

        amount = 0
        supporters = 0
        page_source = driver.page_source
        page_text = driver.find_element(By.TAG_NAME, "body").text

        # 采集金额
        try:
            money_selectors = [
                "[data-investment-info-collected-money]",
                ".project-money-amount",
                ".c-project-status__money .number",
                ".project-fund-raising-price .num"
            ]
            for sel in money_selectors:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                if elems:
                    money_text = "".join(filter(str.isdigit, elems[0].text))
                    if money_text:
                        amount = int(money_text)
                        break
        except Exception as e:
            st.warning(f"金额采集失败: {str(e)}")

        # 采集支持者数
        try:
            # 先从文本匹配
            supp_text_match = re.search(r'サポーター\s*([0-9,]+)\s*人', page_text, re.IGNORECASE)
            if supp_text_match:
                supporters = int(supp_text_match.group(1).replace(',', ''))
            else:
                # 从页面源码匹配JSON数据
                json_patterns = [
                    r'"supporterCount":\s*(\d+)',
                    r'"supporter_count":\s*(\d+)',
                    r'"supporters":\s*(\d+)'
                ]
                for pattern in json_patterns:
                    match = re.search(pattern, page_source, re.DOTALL)
                    if match:
                        supporters = int(match.group(1))
                        break
                else:
                    # 最后尝试CSS选择器
                    supp_selectors = [
                        ".project-supporters__count",
                        ".c-project-status__supporters",
                        ".supporter-count",
                        ".num-supporters"
                    ]
                    for sel in supp_selectors:
                        elem = driver.find_elements(By.CSS_SELECTOR, sel)
                        if elem:
                            supp_text = "".join(filter(str.isdigit, elem[0].text))
                            if supp_text:
                                supporters = int(supp_text)
                                break
        except Exception as e:
            st.warning(f"支持者数采集失败: {str(e)}")

        driver.quit()
        return amount, supporters, None

    except Exception as e:
        return None, None, str(e)

# ================= 数据存储与设置函数 =================
def save_history(project_id, amount, supporters):
    """保存采集的历史数据"""
    c = conn.cursor()
    c.execute("""INSERT INTO history 
                 (project_id, amount, supporters, collected_at) 
                 VALUES (?, ?, ?, ?)""",
              (project_id, amount, supporters, datetime.now(ZoneInfo("Asia/Shanghai"))))
    conn.commit()

def load_settings():
    """加载系统设置"""
    c = conn.cursor()
    c.execute("SELECT auto_running, interval_seconds FROM settings WHERE id = 1")
    row = c.fetchone()
    if row:
        st.session_state.auto_running = bool(row[0])
        st.session_state.global_interval = row[1]
        if st.session_state.auto_running and st.session_state.countdown == 0:
            st.session_state.countdown = st.session_state.global_interval

def save_settings(auto_running, interval_seconds):
    """保存系统设置"""
    c = conn.cursor()
    c.execute("""UPDATE settings 
                 SET auto_running = ?, interval_seconds = ? 
                 WHERE id = 1""",
              (int(auto_running), interval_seconds))
    conn.commit()
    st.session_state.auto_running = auto_running
    st.session_state.global_interval = interval_seconds
    if auto_running and st.session_state.countdown == 0:
        st.session_state.countdown = interval_seconds

# ================= 会话状态初始化 =================
if "auto_running" not in st.session_state:
    st.session_state.auto_running = False
if "countdown" not in st.session_state:
    st.session_state.countdown = 0
if "global_interval" not in st.session_state:
    st.session_state.global_interval = 3600
if "scroll_to_top" not in st.session_state:
    st.session_state.scroll_to_top = False
if "selected_project_id" not in st.session_state:
    st.session_state.selected_project_id = None
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

# 加载系统设置
load_settings()

# ================= 页面配置 =================
st.set_page_config(page_title="Yuuto - Makuake Radar 1.0", layout="wide")

# ================= 页面样式 =================
st.markdown("""
<style>
/* 页头样式 */
.header {
    background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    padding: 1rem;
    border-radius: 0;
    color: white;
    text-align: center;
    margin-bottom: 1rem;
}
/* 表格居中 */
.stDataFrame table td, .stDataFrame table th {
    text-align: center !important;
}
/* 按钮样式 */
.stButton>button {
    width: 100%;
}
</style>
""", unsafe_allow_html=True)

# ================= 页头 =================
st.markdown('<div class="header"><h1>Yuuto - Makuake Radar 1.0</h1><p>Makuake 众筹项目智能监控工具</p></div>', unsafe_allow_html=True)

# ================= 自动滚动到顶部 =================
if st.session_state.scroll_to_top:
    st.components.v1.html("<script>window.scrollTo(0, 0);</script>", height=0)
    st.session_state.scroll_to_top = False

# ================= 数据库下载接口 =================
query_params = st.query_params
if "download_db" in query_params:
    try:
        with open(DB_FILE, "rb") as f:
            db_data = f.read()
        # 自动触发下载
        b64 = base64.b64encode(db_data).decode()
        href = f'<a href="data:application/octet-stream;base64,{b64}" download="makuake.db">点击下载数据库</a>'
        st.markdown(href, unsafe_allow_html=True)
        st.download_button(
            label="下载数据库",
            data=db_data,
            file_name="makuake.db",
            mime="application/octet-stream",
            key="download_db_btn"
        )
        st.stop()
    except FileNotFoundError:
        st.error("❌ 数据库文件不存在！")
        st.stop()

# ================= 侧边栏 =================
with st.sidebar:
    # 管理员验证
    if not st.session_state.is_admin:
        st.title("🔒 管理员验证")
        password = st.text_input("请输入管理员密码", type="password")
        if st.button("验证"):
            # 从Streamlit Secrets读取密码（需在Cloud中配置）
            if password == st.secrets.get("admin_password", "default_password"):
                st.session_state.is_admin = True
                st.success("验证成功！")
                st.rerun()
            else:
                st.error("密码错误！")
        st.divider()
        st.info("您当前处于只读模式，无法操作项目和设置。")
    
    # 管理员模式
    else:
        st.title("⚙️ 控制中心")
        
        # 添加新项目
        with st.expander("➕ 添加新项目", expanded=True):
            new_title = st.text_input("项目名称（自定义）")
            new_url = st.text_input("Makuake 项目 URL")
            
            if st.button("开始监控"):
                if not new_title or not new_url:
                    st.warning("请填写项目名称和URL！")
                elif "makuake.com/project/" not in new_url:
                    st.error("请输入有效的Makuake项目地址！")
                else:
                    c = conn.cursor()
                    try:
                        # 添加项目到数据库
                        c.execute("INSERT INTO projects (url, title, interval) VALUES (?, ?, ?)", 
                                  (new_url, new_title, st.session_state.global_interval))
                        pid = c.lastrowid
                        conn.commit()
                        
                        # 采集初始数据
                        with st.spinner("正在采集初始数据..."):
                            amount, supporters, err = get_makuake_data(new_url)
                            if amount is not None:
                                save_history(pid, amount, supporters)
                                st.success(f"✅ 项目「{new_title}」添加成功！")
                                # 自动开启定时采集
                                save_settings(auto_running=True, interval_seconds=st.session_state.global_interval)
                                st.rerun()
                            else:
                                # 采集失败则删除项目
                                c.execute("DELETE FROM projects WHERE id = ?", (pid,))
                                conn.commit()
                                st.error(f"❌ 初始数据采集失败：{err}")
                    except sqlite3.IntegrityError:
                        st.warning("⚠️ 该项目已在监控列表中！")
        
        st.divider()
        
        # 定时采集设置
        st.subheader("⏰ 定时采集")
        interval_min = st.number_input(
            "采集间隔（分钟）",
            min_value=1,
            value=st.session_state.global_interval // 60,
            step=1
        )
        new_interval = interval_min * 60
        if new_interval != st.session_state.global_interval:
            save_settings(st.session_state.auto_running, new_interval)
        
        # 开启/关闭定时采集
        auto_run = st.checkbox("开启定时采集", value=st.session_state.auto_running)
        if auto_run != st.session_state.auto_running:
            save_settings(auto_run, st.session_state.global_interval)
        
        # 启动/停止按钮
        if st.session_state.auto_running:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("▶️ 启动采集"):
                    st.session_state.countdown = st.session_state.global_interval
                    st.success("定时采集已启动！")
            with col2:
                if st.button("⏹️ 停止采集"):
                    st.session_state.auto_running = False
                    st.session_state.countdown = 0
                    save_settings(False, st.session_state.global_interval)
                    st.info("定时采集已停止！")
            
            # 倒计时显示
            if st.session_state.countdown > 0:
                st.info(f"⏳ 下次采集：{st.session_state.countdown} 秒")
        else:
            st.session_state.countdown = 0
        
        st.divider()
    
    # 项目列表（所有人可见）
    st.subheader("📌 监控项目列表")
    projects_df = pd.read_sql("SELECT * FROM projects", conn)
    if not projects_df.empty:
        selected_title = st.selectbox("选择查看项目", projects_df["title"])
        selected_project = projects_df[projects_df["title"] == selected_title].iloc[0]
        st.session_state.selected_project_id = selected_project["id"]
        
        # 管理员可删除项目
        if st.session_state.is_admin:
            if st.button("🗑️ 删除项目"):
                c = conn.cursor()
                # 删除关联的历史数据
                c.execute("DELETE FROM history WHERE project_id = ?", (selected_project["id"],))
                # 删除项目
                c.execute("DELETE FROM projects WHERE id = ?", (selected_project["id"],))
                conn.commit()
                st.success("项目已删除！")
                st.rerun()
    else:
        st.info("暂无监控项目，请添加新项目。")
        st.session_state.selected_project_id = None

# ================= 主页面：数据展示 =================
if st.session_state.selected_project_id:
    # 加载选中项目的历史数据
    history_df = pd.read_sql(f"""
        SELECT * FROM history 
        WHERE project_id = {st.session_state.selected_project_id}
        ORDER BY collected_at ASC
    """, conn)
    
    if not history_df.empty:
        # 数据预处理
        history_df["collected_at"] = pd.to_datetime(history_df["collected_at"])
        history_df["collected_at_str"] = history_df["collected_at"].dt.strftime("%Y-%m-%d %H:%M:%S")
        
        # 创建双轴图表
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        # 金额曲线
        fig.add_trace(
            go.Scatter(
                x=history_df["collected_at"],
                y=history_df["amount"],
                name="筹集金额（日元）",
                line=dict(color="#667eea", width=3),
                mode="lines+markers"
            ),
            secondary_y=False
        )
        
        # 支持者数曲线
        fig.add_trace(
            go.Scatter(
                x=history_df["collected_at"],
                y=history_df["supporters"],
                name="支持者数",
                line=dict(color="#764ba2", width=3),
                mode="lines+markers"
            ),
            secondary_y=True
        )
        
        # 图表样式
        fig.update_layout(
            title=f"项目：{selected_project['title']} 数据趋势",
            xaxis_title="采集时间",
            height=600,
            legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)")
        )
        fig.update_yaxes(title_text="筹集金额（日元）", secondary_y=False)
        fig.update_yaxes(title_text="支持者数", secondary_y=True)
        
        # 显示图表
        st.plotly_chart(fig, use_container_width=True)
        
        # 显示历史数据表格
        st.subheader("📋 历史采集数据")
        display_df = history_df[["collected_at_str", "amount", "supporters"]].rename(columns={
            "collected_at_str": "采集时间",
            "amount": "筹集金额（日元）",
            "supporters": "支持者数"
        })
        st.dataframe(display_df, use_container_width=True)
        
        # 最新数据卡片
        latest_data = history_df.iloc[-1]
        col1, col2 = st.columns(2)
        with col1:
            st.metric("最新筹集金额", f"{latest_data['amount']:,} 日元", delta=None)
        with col2:
            st.metric("最新支持者数", f"{latest_data['supporters']:,} 人", delta=None)
    else:
        st.info("该项目暂无历史数据，等待首次采集...")
else:
    st.info("请在侧边栏选择一个监控项目查看数据。")

# ================= 定时采集逻辑 =================
if st.session_state.auto_running and st.session_state.countdown > 0:
    # 倒计时递减
    st.session_state.countdown -= 1
    time.sleep(1)
    st.rerun()

# ================= 倒计时结束，执行采集 =================
if st.session_state.auto_running and st.session_state.countdown == 0:
    st.toast("🔄 开始执行定时数据采集...", icon="🔄")
    # 遍历所有项目采集数据
    projects_df = pd.read_sql("SELECT * FROM projects", conn)
    if not projects_df.empty:
        for _, project in projects_df.iterrows():
            amount, supporters, err = get_makuake_data(project["url"])
            if amount is not None:
                save_history(project["id"], amount, supporters)
                st.success(f"✅ {project['title']} 采集成功！")
            else:
                st.error(f"❌ {project['title']} 采集失败：{err}")
    # 重置倒计时
    st.session_state.countdown = st.session_state.global_interval
    st.rerun()

# 关闭数据库连接
conn.close()
