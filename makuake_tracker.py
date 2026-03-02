import streamlit as st
import pandas as pd
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
import hashlib

# ================= Selenium 采集函数 =================
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def get_makuake_data(project_url):
    """使用 Selenium 采集 Makuake 项目的当前金额和支持者数"""
    try:
        if not project_url:
            return None, None, "URL 为空"
        if not project_url.endswith("/"):
            project_url = project_url + "/"

        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
        options.add_argument("--lang=ja-JP")

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager(driver_version="145.0.7632.116").install()),
            options=options
        )
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        driver.get(project_url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(3)

        amount = 0
        supporters = 0
        page_source = driver.page_source
        page_text = driver.find_element(By.TAG_NAME, "body").text

        # 金额采集
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
        except:
            pass

        # 支持者采集
        supp_text_match = re.search(r'サポーター\s*([0-9,]+)\s*人', page_text, re.IGNORECASE)
        if supp_text_match:
            supporters = int(supp_text_match.group(1).replace(',', ''))
        else:
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
                supp_selectors = [
                    ".project-supporters__count",
                    ".c-project-status__supporters",
                    ".supporter-count",
                    ".num-supporters"
                ]
                for sel in supp_selectors:
                    try:
                        elem = driver.find_element(By.CSS_SELECTOR, sel)
                        supp_text = "".join(filter(str.isdigit, elem.text))
                        if supp_text:
                            supporters = int(supp_text)
                            break
                    except:
                        continue

        driver.quit()
        return amount, supporters, None

    except Exception as e:
        return None, None, str(e)

# ================= 数据库初始化（重建表，确保 user_id 存在） =================
def init_db():
    conn = sqlite3.connect('makuake.db')
    c = conn.cursor()
    
    # 删除旧表（避免残留旧结构）
    c.execute('DROP TABLE IF EXISTS history')
    c.execute('DROP TABLE IF EXISTS projects')
    c.execute('DROP TABLE IF EXISTS users')
    
    # 创建新表
    c.execute('''CREATE TABLE users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL)''')
    
    c.execute('''CREATE TABLE projects 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  url TEXT,
                  title TEXT,
                  interval INTEGER,
                  FOREIGN KEY(user_id) REFERENCES users(id))''')
    
    c.execute('''CREATE TABLE history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  project_id INTEGER,
                  amount INTEGER,
                  supporters INTEGER,
                  collected_at TIMESTAMP,
                  FOREIGN KEY(user_id) REFERENCES users(id))''')
    conn.commit()
    return conn

conn = init_db()

# ================= 用户认证函数 =================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate_user(username, password):
    c = conn.cursor()
    c.execute("SELECT id, password FROM users WHERE username = ?", (username,))
    result = c.fetchone()
    if result and result[1] == hash_password(password):
        return result[0]
    return None

def register_user(username, password):
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                  (username, hash_password(password)))
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return None

# ================= 保存历史数据（带 user_id） =================
def save_history(user_id, project_id, amount, supporters):
    c = conn.cursor()
    c.execute("INSERT INTO history (user_id, project_id, amount, supporters, collected_at) VALUES (?, ?, ?, ?, ?)",
              (user_id, project_id, amount, supporters, datetime.now(ZoneInfo("Asia/Shanghai"))))
    conn.commit()

# ================= 会话状态初始化 =================
if "auto_running" not in st.session_state:
    st.session_state.auto_running = False
if "countdown" not in st.session_state:
    st.session_state.countdown = 0
if "global_interval" not in st.session_state:
    st.session_state.global_interval = 3600
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_id = None
    st.session_state.username = None

# ================= 页面配置 =================
st.set_page_config(page_title="Yuuto - Makuake Radar 1.0", layout="wide")

# ================= 应用页头 =================
st.markdown("""
<div style="background: linear-gradient(90deg, #667eea 0%, #764ba2 100%); padding: 1rem; border-radius: 0; color: white; text-align: center; margin-bottom: 1rem;">
    <h1 style="margin:0; font-size: 1.8rem;">Yuuto - Makuake Radar 1.0</h1>
    <p style="margin:0; opacity:0.9;">Makuake 众筹项目智能监控工具</p>
</div>
""", unsafe_allow_html=True)

# ================= 添加自定义CSS使表格居中对齐 =================
st.markdown("""
<style>
    .stDataFrame table td {
        text-align: center !important;
    }
    .stDataFrame table th {
        text-align: center !important;
    }
</style>
""", unsafe_allow_html=True)

# ================= 侧边栏（登录/注册 + 主功能） =================
with st.sidebar:
    # 如果未登录，显示登录/注册界面
    if not st.session_state.logged_in:
        st.title("🔐 用户登录")
        
        tab_login, tab_register = st.tabs(["登录", "注册"])
        
        with tab_login:
            with st.form("login_form"):
                login_user = st.text_input("用户名")
                login_pass = st.text_input("密码", type="password")
                if st.form_submit_button("登录", use_container_width=True):
                    user_id = authenticate_user(login_user, login_pass)
                    if user_id:
                        st.session_state.logged_in = True
                        st.session_state.user_id = user_id
                        st.session_state.username = login_user
                        st.rerun()
                    else:
                        st.error("用户名或密码错误")
        
        with tab_register:
            with st.form("register_form"):
                reg_user = st.text_input("用户名")
                reg_pass = st.text_input("密码", type="password")
                reg_confirm = st.text_input("确认密码", type="password")
                if st.form_submit_button("注册", use_container_width=True):
                    if reg_pass != reg_confirm:
                        st.error("两次密码不一致")
                    elif len(reg_user) < 3:
                        st.error("用户名至少3个字符")
                    elif len(reg_pass) < 3:
                        st.error("密码至少3个字符")
                    else:
                        user_id = register_user(reg_user, reg_pass)
                        if user_id:
                            # 注册成功后自动登录
                            st.session_state.logged_in = True
                            st.session_state.user_id = user_id
                            st.session_state.username = reg_user
                            st.rerun()
                        else:
                            st.error("用户名已存在")
        
        st.stop()  # 未登录时不再显示主界面
    
    # 已登录，显示主功能
    st.title(f"👋 欢迎, {st.session_state.username}")
    st.divider()
    
    # 添加新项目
    st.subheader("添加新项目")
    new_title = st.text_input("项目名称（自定义）")
    new_url = st.text_input("Makuake 项目 URL")
    
 if st.button("开始监控", use_container_width=True):
    if not new_title or not new_url:
        st.warning("请填写项目名称和 URL")
    elif "makuake.com/project/" not in new_url:
        st.error("请输入有效的 Makuake 项目地址")
    else:
        c = conn.cursor()
        try:
            # 插入项目
            c.execute("INSERT INTO projects (user_id, url, title, interval) VALUES (?, ?, ?, ?)", 
                      (st.session_state.user_id, new_url, new_title, st.session_state.global_interval))
            pid = c.lastrowid
            conn.commit()
            
            # 采集初始数据
            with st.spinner("正在采集初始数据..."):
                try:
                    amount, supporters, err = get_makuake_data(new_url)
                    if amount is not None:
                        save_history(st.session_state.user_id, pid, amount, supporters)
                        st.success(f"项目 {new_title} 添加成功，已采集初始数据")
                        st.rerun()
                    else:
                        # 采集失败，删除刚插入的项目
                        c.execute("DELETE FROM projects WHERE id = ?", (pid,))
                        conn.commit()
                        st.error(f"采集失败: {err}")
                except Exception as e:
                    # 采集过程发生异常
                    c.execute("DELETE FROM projects WHERE id = ?", (pid,))
                    conn.commit()
                    st.error(f"采集过程异常: {str(e)}")
        except sqlite3.IntegrityError:
            st.warning("该项目已在监控列表中")
        except Exception as e:
            # 插入项目时发生其他异常
            st.error(f"添加项目失败: {str(e)}")
    
    st.divider()
    
    # 项目列表（手动执行查询，避免 pd.read_sql 参数问题）
    st.subheader("项目列表")
    try:
        cursor = conn.execute("SELECT * FROM projects WHERE user_id = ?", (st.session_state.user_id,))
        data = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        projects_df = pd.DataFrame(data, columns=columns)
    except Exception as e:
        st.error(f"查询项目失败: {e}")
        st.stop()
    
    if not projects_df.empty:
        selected_title = st.selectbox("选择要查看的项目", projects_df['title'])
        selected_project = projects_df[projects_df['title'] == selected_title].iloc[0]
        if st.button("🗑️ 删除当前项目", type="secondary"):
            c = conn.cursor()
            c.execute("DELETE FROM history WHERE user_id = ? AND project_id = ?", 
                      (st.session_state.user_id, int(selected_project['id'])))
            c.execute("DELETE FROM projects WHERE user_id = ? AND id = ?", 
                      (st.session_state.user_id, int(selected_project['id'])))
            conn.commit()
            st.rerun()
    else:
        st.info("暂无监控项目")
        # 后续代码依赖 selected_project，需要提前退出或赋空值
        selected_project = None
    
    st.divider()
    
    # 定时采集
    st.subheader("⏰ 定时采集")
    interval_min = st.number_input("采集间隔 (分钟)", min_value=1, value=st.session_state.global_interval // 60, step=1)
    st.session_state.global_interval = interval_min * 60
    
    auto_run = st.checkbox("开启定时采集", value=st.session_state.auto_running)
    st.session_state.auto_running = auto_run
    
    if st.session_state.auto_running:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ 启动", use_container_width=True):
                st.session_state.countdown = st.session_state.global_interval
                st.success("定时采集已启动")
        with col2:
            if st.button("⏹️ 停止", use_container_width=True):
                st.session_state.auto_running = False
                st.session_state.countdown = 0
                st.info("定时采集已停止")
        
        if st.session_state.countdown > 0:
            st.info(f"⏳ 下次采集: {st.session_state.countdown} 秒")
    else:
        st.session_state.countdown = 0
    
    st.divider()
    
    # 登出按钮
    if st.button("🚪 登出", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user_id = None
        st.session_state.username = None
        st.rerun()

# ================= 主界面（仅登录用户可见） =================
if selected_project is not None:
    st.title(f"📊 {selected_project['title']}")
    st.caption(f"🔗 [访问原始项目]({selected_project['url']})")

    # 读取历史数据（手动执行）
    try:
        cursor = conn.execute(
            "SELECT * FROM history WHERE user_id = ? AND project_id = ? ORDER BY collected_at DESC",
            (st.session_state.user_id, int(selected_project['id']))
        )
        data = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        history_df = pd.DataFrame(data, columns=columns)
        if not history_df.empty and 'collected_at' in history_df.columns:
            history_df['collected_at'] = pd.to_datetime(history_df['collected_at'])
    except Exception as e:
        st.error(f"查询历史数据失败: {e}")
        st.stop()
    
    if not history_df.empty:
        latest = history_df.iloc[0]
        prev = history_df.iloc[1] if len(history_df) > 1 else latest
        
        col1, col2, col3 = st.columns(3)
        with col1:
            delta_amount = latest['amount'] - prev['amount']
            st.metric("当前筹得额 (円)", f"¥{latest['amount']:,}", f"{delta_amount:+,}")
        with col2:
            delta_supporters = latest['supporters'] - prev['supporters']
            st.metric("支持者人数", f"{latest['supporters']:,} 人", f"{delta_supporters:+,}")
        with col3:
            st.metric("采集状态", "运行中" if st.session_state.auto_running else "手动", 
                      "定时" if st.session_state.auto_running else "手动")

        st.divider()
        st.subheader("📈 增长趋势分析")
        
        view_option = st.radio(
            "选择时间范围",
            ["全程", "30天", "7天", "今天", "自定义日期"],
            horizontal=True,
            key="view_selector"
        )
        
        df_raw = history_df.sort_values('collected_at').copy()
        df_raw.set_index('collected_at', inplace=True)
        
        if view_option == "全程":
            df_plot = df_raw.resample('D').last().dropna()
            time_unit = "天"
        elif view_option == "30天":
            cutoff = df_raw.index.max() - timedelta(days=30)
            df_filtered = df_raw[df_raw.index >= cutoff]
            df_plot = df_filtered.resample('D').last().dropna()
            time_unit = "天"
        elif view_option == "7天":
            cutoff = df_raw.index.max() - timedelta(days=7)
            df_filtered = df_raw[df_raw.index >= cutoff]
            df_plot = df_filtered.resample('D').last().dropna()
            time_unit = "天"
        elif view_option == "今天":
            today = df_raw.index.max().date()
            df_filtered = df_raw[df_raw.index.date == today]
            df_plot = df_filtered.resample('H').last().dropna()
            time_unit = "小时"
        elif view_option == "自定义日期":
            available_dates = sorted(set(df_raw.index.date))
            if available_dates:
                default_date = available_dates[-1]
                selected_date = st.date_input("选择日期", value=default_date, min_value=available_dates[0], max_value=available_dates[-1])
                df_filtered = df_raw[df_raw.index.date == selected_date]
                if not df_filtered.empty:
                    df_plot = df_filtered.resample('H').last().dropna()
                    time_unit = "小时"
                else:
                    st.warning("所选日期无数据")
                    df_plot = pd.DataFrame()
            else:
                st.warning("无可用日期")
                df_plot = pd.DataFrame()
        
        if not df_plot.empty:
            df_plot['金额增长'] = df_plot['amount'].diff().fillna(0).astype(int)
            df_plot['支持者增长'] = df_plot['supporters'].diff().fillna(0).astype(int)
            
            df_plot.reset_index(inplace=True)
            df_plot.rename(columns={'index': 'collected_at'}, inplace=True)
            
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            
            fig.add_trace(
                go.Scatter(
                    x=df_plot['collected_at'],
                    y=df_plot['amount'],
                    name="筹得金额",
                    line=dict(color='#14b8a6', width=3),
                    mode='lines+markers',
                    marker=dict(size=8)
                ),
                secondary_y=False
            )
            
            colors = ['#10b981' if val >= 0 else '#ef4444' for val in df_plot['金额增长']]
            bar_width = 1.0
            fig.add_trace(
                go.Bar(
                    x=df_plot['collected_at'],
                    y=df_plot['金额增长'],
                    name="金额增量",
                    marker=dict(color=colors, line=dict(width=1.5, color='#333')),
                    opacity=0.8,
                    width=bar_width
                ),
                secondary_y=True
            )
            
            fig.update_layout(
                hovermode="x unified",
                template="plotly_white",
                height=500,
                margin=dict(l=40, r=40, t=20, b=80),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                bargap=0.02
            )
            
            if time_unit == "天":
                fig.update_xaxes(tickformat="%m-%d", tickangle=45, nticks=min(15, len(df_plot)))
            else:
                fig.update_xaxes(
                    tickformat="%H:%M",
                    tickangle=45,
                    dtick=3600000,
                    tickmode='linear'
                )
            
            fig.update_yaxes(tickformat=',d', secondary_y=False)
            fig.update_yaxes(tickformat='+,d', secondary_y=True)
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("所选时间范围内无数据")

        st.divider()
        col_a, col_b = st.columns([2, 1])
        with col_a:
            st.subheader("📋 采集历史明细")
        with col_b:
            if st.button("🔄 立即同步", use_container_width=True):
                with st.spinner("正在采集最新数据..."):
                    amount, supporters, err = get_makuake_data(selected_project['url'])
                    if amount is not None:
                        save_history(st.session_state.user_id, selected_project['id'], amount, supporters)
                        st.success("同步成功")
                        st.rerun()
                    else:
                        st.error(f"采集失败: {err}")

        # 准备表格数据
        df_display = history_df.sort_values('collected_at').copy()
        df_display['金额增长'] = df_display['amount'].diff().fillna(0).astype(int)
        df_display['支持者增长'] = df_display['supporters'].diff().fillna(0).astype(int)
        df_display = df_display.sort_values('collected_at', ascending=False)

        display_cols = ['collected_at', 'amount', 'supporters', '金额增长', '支持者增长']
        display_df = df_display[display_cols].copy()
        display_df.rename(columns={
            'collected_at': '采集时间',
            'amount': '応援購入総額',
            'supporters': 'サポーター',
            '金额增长': '金額増加',
            '支持者增长': 'サポーター増加'
        }, inplace=True)

        items_per_page = 10
        total_pages = (len(display_df) // items_per_page) + 1
        page = st.number_input("页码", min_value=1, max_value=total_pages, step=1)
        start_idx = (page - 1) * items_per_page
        page_df = display_df.iloc[start_idx : start_idx + items_per_page]

        def highlight_change(val):
            if val > 0:
                return 'color: #10b981; font-weight: bold'
            elif val < 0:
                return 'color: #ef4444; font-weight: bold'
            else:
                return ''

        styled_df = page_df.style.format({
            '采集时间': lambda x: x.strftime('%Y/%m/%d %H:%M') if pd.notna(x) else '',
            '応援購入総額': '¥{:,.0f}',
            'サポーター': '{:,.0f} 人',
            '金額増加': lambda x: f'+¥{x:,.0f}' if x > 0 else (f'¥{x:,.0f}' if x < 0 else '0'),
            'サポーター増加': lambda x: f'+{x:,.0f}' if x > 0 else (f'{x:,.0f}' if x < 0 else '0')
        }).applymap(highlight_change, subset=['金額増加', 'サポーター増加'])

        st.dataframe(styled_df, use_container_width=True, hide_index=True)

        csv = history_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 导出完整历史记录 (CSV)", csv, f"history_{selected_project['id']}.csv", "text/csv")

    else:
        st.info("暂无历史数据")

else:
    st.info("请在左侧侧边栏添加您的第一个监控项目。")

st.divider()
st.caption("Yuuto - Makuake Radar 1.0 | 时区 Asia/Shanghai | 采集引擎：Selenium + ChromeDriver")

# ================= 定时采集逻辑（仅对当前用户） =================
if st.session_state.auto_running and st.session_state.countdown > 0 and st.session_state.logged_in:
    time.sleep(1)
    st.session_state.countdown -= 1
    if st.session_state.countdown == 0:
        with st.spinner("正在执行定时采集所有项目..."):
            try:
                cursor = conn.execute("SELECT * FROM projects WHERE user_id = ?", (st.session_state.user_id,))
                data = cursor.fetchall()
                columns = [description[0] for description in cursor.description]
                projects = pd.DataFrame(data, columns=columns)
            except Exception as e:
                st.error(f"定时采集查询失败: {e}")
                projects = pd.DataFrame()
            
            for _, row in projects.iterrows():
                amount, supporters, err = get_makuake_data(row['url'])
                if amount is not None:
                    save_history(st.session_state.user_id, row['id'], amount, supporters)
        st.session_state.countdown = st.session_state.global_interval
        st.rerun()
    else:
        st.rerun()


