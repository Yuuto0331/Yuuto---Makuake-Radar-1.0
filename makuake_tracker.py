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
import base64
import requests

# ================= 核心配置 =================
DB_FILE = "makuake.db"
GITHUB_REPO = "Yuuto0331/Yuuto---Makuake-Radar-1.0"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# ================= 自动恢复备份 =================
def auto_restore_from_github():
    def is_db_healthy():
        if not os.path.exists(DB_FILE):
            return False
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.execute("SELECT 1 FROM projects LIMIT 1")
            conn.close()
            return True
        except:
            return False

    if is_db_healthy():
        return

    st.toast("⚠️ 数据库异常，正在恢复备份...", icon="⚠️")
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/backups"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        
        res = requests.get(url, headers=headers, timeout=30)
        res.raise_for_status()
        backups = res.json()
        backup_dirs = [b for b in backups if b["type"] == "dir"]
        
        if not backup_dirs:
            st.error("❌ 无备份文件夹")
            return
        
        latest_dir = sorted(backup_dirs, key=lambda x: x["name"], reverse=True)[0]
        files_res = requests.get(latest_dir["url"], headers=headers, timeout=30)
        files_res.raise_for_status()
        db_files = [f for f in files_res.json() if f["name"].startswith("makuake_full_") and f["name"].endswith(".db")]
        
        if not db_files:
            st.error("❌ 无数据库备份文件")
            return
        
        db_data = requests.get(db_files[0]["download_url"], headers=headers, timeout=30).content
        with open(DB_FILE, "wb") as f:
            f.write(db_data)
        
        st.success("✅ 备份恢复成功！", icon="✅")
    except Exception as e:
        st.error(f"❌ 恢复失败：{str(e)}", icon="❌")

# ================= 数据库初始化 =================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS projects 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE, title TEXT, interval INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, amount INTEGER, 
                  supporters INTEGER, collected_at TIMESTAMP, FOREIGN KEY(project_id) REFERENCES projects(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings 
                 (id INTEGER PRIMARY KEY CHECK (id = 1), auto_running INTEGER, interval_seconds INTEGER)''')
    c.execute("INSERT OR IGNORE INTO settings (id, auto_running, interval_seconds) VALUES (1, 0, 3600)")
    conn.commit()
    return conn

conn = init_db()
auto_restore_from_github()

# ================= Selenium 采集函数 =================
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def get_makuake_data(project_url):
    try:
        if not project_url or "makuake.com/project/" not in project_url:
            return None, None, "无效的URL"
        
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
        
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager(driver_version="145.0.7632.116").install()),
            options=options
        )
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        driver.get(project_url)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(3)

        amount = 0
        supporters = 0
        page_text = driver.find_element(By.TAG_NAME, "body").text
        page_source = driver.page_source

        # 采集金额
        money_selectors = ["[data-investment-info-collected-money]", ".project-money-amount", ".c-project-status__money .number"]
        for sel in money_selectors:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            if elems:
                money_text = "".join(filter(str.isdigit, elems[0].text))
                if money_text:
                    amount = int(money_text)
                    break

        # 采集支持者
        supp_match = re.search(r'サポーター\s*([0-9,]+)\s*人', page_text, re.IGNORECASE)
        if supp_match:
            supporters = int(supp_match.group(1).replace(',', ''))
        else:
            json_patterns = [r'"supporterCount":\s*(\d+)', r'"supporter_count":\s*(\d+)']
            for pat in json_patterns:
                match = re.search(pat, page_source)
                if match:
                    supporters = int(match.group(1))
                    break

        driver.quit()
        return amount, supporters, None
    except Exception as e:
        return None, None, str(e)

# ================= 辅助函数 =================
def save_history(project_id, amount, supporters):
    c = conn.cursor()
    c.execute("INSERT INTO history (project_id, amount, supporters, collected_at) VALUES (?, ?, ?, ?)",
              (project_id, amount, supporters, datetime.now(ZoneInfo("Asia/Shanghai"))))
    conn.commit()

def load_settings():
    c = conn.cursor()
    c.execute("SELECT auto_running, interval_seconds FROM settings WHERE id = 1")
    row = c.fetchone()
    if row:
        st.session_state.auto_running = bool(row[0])
        st.session_state.global_interval = row[1]
        if st.session_state.auto_running and st.session_state.countdown == 0:
            st.session_state.countdown = st.session_state.global_interval

def save_settings(auto_running, interval_seconds):
    c = conn.cursor()
    c.execute("UPDATE settings SET auto_running = ?, interval_seconds = ? WHERE id = 1",
              (int(auto_running), interval_seconds))
    conn.commit()
    st.session_state.auto_running = auto_running
    st.session_state.global_interval = interval_seconds
    if auto_running and st.session_state.countdown == 0:
        st.session_state.countdown = interval_seconds

# ================= 会话状态 =================
for key in ["auto_running", "countdown", "global_interval", "scroll_to_top", "selected_project_id", "is_admin"]:
    if key not in st.session_state:
        st.session_state[key] = False if key != "countdown" else 0

load_settings()

# ================= 页面配置 =================
st.set_page_config(page_title="Yuuto - Makuake Radar 1.0", layout="wide")
st.markdown("""
<style>
.header {background: linear-gradient(90deg, #667eea 0%, #764ba2 100%); padding: 1rem; color: white; text-align: center; margin-bottom: 1rem;}
.stDataFrame table td, .stDataFrame table th {text-align: center !important;}
.stButton>button {width: 100%;}
</style>
""", unsafe_allow_html=True)
st.markdown('<div class="header"><h1>Yuuto - Makuake Radar 1.0</h1><p>Makuake 众筹监控工具</p></div>', unsafe_allow_html=True)

# ================= 数据库下载接口 =================
if "download_db" in st.query_params:
    try:
        with open(DB_FILE, "rb") as f:
            db_data = f.read()
        st.download_button("下载数据库", db_data, "makuake.db", "application/octet-stream")
        st.stop()
    except FileNotFoundError:
        st.error("数据库文件不存在")
        st.stop()

# ================= 侧边栏 =================
with st.sidebar:
    # 管理员验证
    if not st.session_state.is_admin:
        st.title("🔒 管理员验证")
        password = st.text_input("密码", type="password")
        if st.button("验证"):
            if password == st.secrets.get("admin_password", "123456"):
                st.session_state.is_admin = True
                st.success("验证成功")
                st.rerun()
            else:
                st.error("密码错误")
        st.info("只读模式，无法操作")
    else:
        # 添加项目
        st.title("⚙️ 控制中心")
        with st.expander("➕ 添加新项目", expanded=True):
            new_title = st.text_input("项目名称")
            new_url = st.text_input("Makuake URL")
            if st.button("开始监控"):
                if not new_title or not new_url:
                    st.warning("请填写完整信息")
                else:
                    c = conn.cursor()
                    try:
                        c.execute("INSERT INTO projects (url, title, interval) VALUES (?, ?, ?)", (new_url, new_title, st.session_state.global_interval))
                        pid = c.lastrowid
                        conn.commit()
                        amount, supporters, err = get_makuake_data(new_url)
                        if amount:
                            save_history(pid, amount, supporters)
                            st.success(f"✅ {new_title} 添加成功")
                            st.rerun()
                        else:
                            c.execute("DELETE FROM projects WHERE id = ?", (pid,))
                            conn.commit()
                            st.error(f"❌ 采集失败：{err}")
                    except sqlite3.IntegrityError:
                        st.warning("⚠️ 项目已存在")
            
            # 定时设置
            st.divider()
            st.subheader("⏰ 定时采集")
            interval_min = st.number_input("间隔（分钟）", min_value=1, value=st.session_state.global_interval//60)
            if interval_min * 60 != st.session_state.global_interval:
                save_settings(st.session_state.auto_running, interval_min*60)
            
            auto_run = st.checkbox("开启定时", value=st.session_state.auto_running)
            if auto_run != st.session_state.auto_running:
                save_settings(auto_run, st.session_state.global_interval)
            
            if st.session_state.auto_running:
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("▶️ 启动"):
                        st.session_state.countdown = st.session_state.global_interval
                        st.success("启动成功")
                with col2:
                    if st.button("⏹️ 停止"):
                        st.session_state.auto_running = False
                        st.session_state.countdown = 0
                        save_settings(False, st.session_state.global_interval)
                        st.info("已停止")
                st.info(f"下次采集：{st.session_state.countdown} 秒")
        
        # 项目列表
        st.divider()
        st.subheader("📌 项目列表")
        projects_df = pd.read_sql("SELECT * FROM projects", conn)
        if not projects_df.empty:
            selected_title = st.selectbox("选择项目", projects_df["title"])
            selected_project = projects_df[projects_df["title"] == selected_title].iloc[0]
            st.session_state.selected_project_id = selected_project["id"]
            
            if st.session_state.is_admin and st.button("🗑️ 删除项目"):
                c = conn.cursor()
                c.execute("DELETE FROM history WHERE project_id = ?", (selected_project["id"],))
                c.execute("DELETE FROM projects WHERE id = ?", (selected_project["id"],))
                conn.commit()
                st.success("已删除")
                st.rerun()
        else:
            st.info("暂无项目")
            st.session_state.selected_project_id = None

# ================= 主页面 =================
if st.session_state.selected_project_id:
    history_df = pd.read_sql(f"""
        SELECT * FROM history WHERE project_id = {st.session_state.selected_project_id} ORDER BY collected_at ASC
    """, conn)
    if not history_df.empty:
        history_df["collected_at"] = pd.to_datetime(history_df["collected_at"])
        
        # 绘图
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=history_df["collected_at"], y=history_df["amount"], name="金额（日元）", line=dict(color="#667eea", width=3)), secondary_y=False)
        fig.add_trace(go.Scatter(x=history_df["collected_at"], y=history_df["supporters"], name="支持者数", line=dict(color="#764ba2", width=3)), secondary_y=True)
        fig.update_layout(title=f"项目：{selected_project['title']} 趋势", height=600, xaxis_title="采集时间")
        fig.update_yaxes(title_text="金额（日元）", secondary_y=False)
        fig.update_yaxes(title_text="支持者数", secondary_y=True)
        st.plotly_chart(fig, use_container_width=True)
        
        # 数据表格
        st.subheader("📋 历史数据")
        display_df = history_df[["collected_at", "amount", "supporters"]].rename(columns={
            "collected_at": "采集时间", "amount": "金额（日元）", "supporters": "支持者数"
        })
        st.dataframe(display_df, use_container_width=True)
        
        # 最新数据
        latest = history_df.iloc[-1]
        col1, col2 = st.columns(2)
        with col1:
            st.metric("最新金额", f"{latest['amount']:,} 日元")
        with col2:
            st.metric("最新支持者", f"{latest['supporters']:,} 人")
    else:
        st.info("暂无历史数据")
else:
    st.info("请选择一个项目查看")

# ================= 定时采集逻辑 =================
if st.session_state.auto_running and st.session_state.countdown > 0:
    st.session_state.countdown -= 1
    time.sleep(1)
    st.rerun()

if st.session_state.auto_running and st.session_state.countdown == 0:
    st.toast("🔄 开始采集数据...")
    projects_df = pd.read_sql("SELECT * FROM projects", conn)
    if not projects_df.empty:
        for _, proj in projects_df.iterrows():
            amount, supporters, err = get_makuake_data(proj["url"])
            if amount:
                save_history(proj["id"], amount, supporters)
                st.success(f"✅ {proj['title']} 采集成功")
            else:
                st.error(f"❌ {proj['title']} 采集失败：{err}")
    st.session_state.countdown = st.session_state.global_interval
    st.rerun()

conn.close()
