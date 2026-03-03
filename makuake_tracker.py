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

# ================= 数据库初始化（含设置表） =================
def init_db():
    conn = sqlite3.connect('makuake.db')
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

load_settings()

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

# ================= 自动滚动到顶部的逻辑 =================
if st.session_state.scroll_to_top:
    st.components.v1.html(
        """
        <script>
            window.scrollTo(0, 0);
        </script>
        """,
        height=0,
    )
    st.session_state.scroll_to_top = False

# ================= 数据库下载接口（无密码） =================
query_params = st.query_params
if "download_db" in query_params:
    try:
        with open("makuake.db", "rb") as f:
            db_data = f.read()
        st.download_button(
            label="点击下载数据库（如果未自动下载）",
            data=db_data,
            file_name="makuake.db",
            mime="application/octet-stream"
        )
        st.stop()
    except FileNotFoundError:
        st.error("数据库文件不存在")
        st.stop()

# ================= 侧边栏 =================
with st.sidebar:
    # ---------- 管理员验证 ----------
    if not st.session_state.is_admin:
        st.title("🔒 管理员验证")
        password = st.text_input("请输入管理员密码", type="password")
        if st.button("验证", use_container_width=True):
            if password == st.secrets["admin_password"]:
                st.session_state.is_admin = True
                st.success("验证成功")
                st.rerun()
            else:
                st.error("密码错误")
        st.divider()
        st.info("您当前处于只读模式，无法进行操作。")
        # 只读状态下隐藏所有操作，但项目列表仍可查看（删除按钮隐藏）
    
    else:
        # 已验证，显示完整控制中心
        st.title("⚙️ 控制中心")
        
        st.divider()
        
        with st.expander("➕ 添加新项目", expanded=True):
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
                        c.execute("INSERT INTO projects (url, title, interval) VALUES (?, ?, ?)", 
                                  (new_url, new_title, st.session_state.global_interval))
                        pid = c.lastrowid
                        conn.commit()
                        
                        with st.spinner("正在采集初始数据..."):
                            amount, supporters, err = get_makuake_data(new_url)
                            if amount is not None:
                                save_history(pid, amount, supporters)
                                st.success(f"项目 {new_title} 添加成功，已采集初始数据")
                                save_settings(auto_running=True, interval_seconds=3600)
                                st.rerun()
                            else:
                                c.execute("DELETE FROM projects WHERE id = ?", (pid,))
                                conn.commit()
                                st.error(f"初始数据采集失败: {err}")
                    except sqlite3.IntegrityError:
                        st.warning("该项目已在监控列表中")
        
        st.divider()
        
        st.subheader("⏰ 定时采集")
        interval_min = st.number_input(
            "采集间隔 (分钟)",
            min_value=1,
            value=st.session_state.global_interval // 60,
            step=1,
            key="interval_input"
        )
        new_interval = interval_min * 60
        if new_interval != st.session_state.global_interval:
            save_settings(auto_running=st.session_state.auto_running, interval_seconds=new_interval)
        
        auto_run = st.checkbox("开启定时采集", value=st.session_state.auto_running, key="auto_checkbox")
        if auto_run != st.session_state.auto_running:
            save_settings(auto_running=auto_run, interval_seconds=st.session_state.global_interval)
        
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
                    save_settings(auto_running=False, interval_seconds=st.session_state.global_interval)
                    st.info("定时采集已停止")
            
            if st.session_state.countdown > 0:
                st.info(f"⏳ 下次采集: {st.session_state.countdown} 秒")
        else:
            st.session_state.countdown = 0
        
        st.divider()
    
    # ---------- 项目列表（始终显示，但删除按钮仅管理员可见） ----------
    st.subheader("📌 项目列表")
    projects_df = pd.read_sql("SELECT * FROM projects", conn)
    if not projects_df.empty:
        selected_title = st.selectbox("选择要查看的项目", projects_df['title'])
        selected_project = projects_df[projects_df['title'] == selected_title].iloc[0]
        # 仅管理员显示删除按钮
        if st.session_state.is_admin:
            if st.button("🗑️ 删除当前项目", type="secondary"):
                c = conn.cursor()
                c.execute("DELETE FROM history WHERE project_id = ?", (int(selected_project['id']),))
                c.execute("DELETE FROM projects WHERE id = ?", (int(selected_project['id']),))
                conn.commit()
                st.rerun()
    else:
        st.info("暂无监控项目")
        selected_project = None

# ================= 项目总览（所有项目对比） =================
if not projects_df.empty:
    with st.expander("📋 项目总览（点击展开对比）", expanded=False):
        overview_data = []
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        yesterday = today - timedelta(days=1)
        
        for _, row in projects_df.iterrows():
            pid = row['id']
            title = row['title']
            hist = pd.read_sql(
                f"SELECT amount, supporters, collected_at FROM history WHERE project_id = {pid} ORDER BY collected_at",
                conn,
                parse_dates=['collected_at']
            )
            if hist.empty:
                overview_data.append({
                    "项目名称": title,
                    "总金额": 0,
                    "总支持者": 0,
                    "今日金额增量": 0,
                    "今日支持者增量": 0,
                    "昨日金额增量": 0,
                    "昨日支持者增量": 0
                })
                continue
            
            latest = hist.iloc[-1]
            total_amount = latest['amount']
            total_supporters = latest['supporters']
            
            today_data = hist[hist['collected_at'].dt.date == today]
            if len(today_data) >= 2:
                today_amount_inc = today_data['amount'].iloc[-1] - today_data['amount'].iloc[0]
                today_supporters_inc = today_data['supporters'].iloc[-1] - today_data['supporters'].iloc[0]
            elif len(today_data) == 1:
                today_amount_inc = 0
                today_supporters_inc = 0
            else:
                today_amount_inc = 0
                today_supporters_inc = 0
            
            yesterday_data = hist[hist['collected_at'].dt.date == yesterday]
            if len(yesterday_data) >= 2:
                yesterday_amount_inc = yesterday_data['amount'].iloc[-1] - yesterday_data['amount'].iloc[0]
                yesterday_supporters_inc = yesterday_data['supporters'].iloc[-1] - yesterday_data['supporters'].iloc[0]
            elif len(yesterday_data) == 1:
                yesterday_amount_inc = 0
                yesterday_supporters_inc = 0
            else:
                yesterday_amount_inc = 0
                yesterday_supporters_inc = 0
            
            overview_data.append({
                "项目名称": title,
                "总金额": total_amount,
                "总支持者": total_supporters,
                "今日金额增量": today_amount_inc,
                "今日支持者增量": today_supporters_inc,
                "昨日金额增量": yesterday_amount_inc,
                "昨日支持者增量": yesterday_supporters_inc
            })
        
        overview_df = pd.DataFrame(overview_data)
        st.dataframe(
            overview_df.style.format({
                "总金额": "¥{:,.0f}",
                "总支持者": "{:,.0f}",
                "今日金额增量": "{:+,.0f}",
                "今日支持者增量": "{:+,.0f}",
                "昨日金额增量": "{:+,.0f}",
                "昨日支持者增量": "{:+,.0f}"
            }),
            use_container_width=True,
            hide_index=True
        )

# ================= 主界面 =================
if selected_project is not None:
    st.title(f"📊 {selected_project['title']}")
    st.caption(f"🔗 [访问原始项目]({selected_project['url']})")

    history_df = pd.read_sql(
        f"SELECT * FROM history WHERE project_id = {selected_project['id']} ORDER BY collected_at DESC", 
        conn, 
        parse_dates=['collected_at']
    )
    
    if not history_df.empty:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        today_data = history_df[history_df['collected_at'].dt.date == today].sort_values('collected_at')
        if len(today_data) >= 2:
            today_amount_inc = today_data['amount'].iloc[-1] - today_data['amount'].iloc[0]
            today_supporters_inc = today_data['supporters'].iloc[-1] - today_data['supporters'].iloc[0]
        elif len(today_data) == 1:
            today_amount_inc = 0
            today_supporters_inc = 0
        else:
            today_amount_inc = None
            today_supporters_inc = None

        latest = history_df.iloc[0]
        prev = history_df.iloc[1] if len(history_df) > 1 else latest
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            delta_amount = latest['amount'] - prev['amount']
            st.metric("当前筹得额 (円)", f"¥{latest['amount']:,}", delta=f"{delta_amount:+,}")
        with col2:
            delta_supporters = latest['supporters'] - prev['supporters']
            st.metric("支持者人数", f"{latest['supporters']:,} 人", delta=f"{delta_supporters:+,}")
        with col3:
            delta_display = f"{today_amount_inc:+,}" if today_amount_inc is not None else "暂无数据"
            st.metric("今日销售增量 (円)", delta_display)
        with col4:
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
            today_data = df_raw[df_raw.index.date == df_raw.index.max().date()]
            df_plot = today_data.resample('H').last().dropna()
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
                    width=bar_width,
                    customdata=df_plot['支持者增长'],
                    hovertemplate=
                        "<b>金额增量</b>: %{y:+,d} 円<br>" +
                        "<b>支持者增量</b>: %{customdata:+,d} 人<br>" +
                        "<extra></extra>"
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
                        save_history(selected_project['id'], amount, supporters)
                        st.success("同步成功")
                        st.rerun()
                    else:
                        st.error(f"采集失败: {err}")

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
    st.warning("请在左侧侧边栏添加您的第一个监控项目。")

st.divider()
st.caption("Yuuto - Makuake Radar 1.0 | 时区 Asia/Shanghai | 采集引擎：Selenium + ChromeDriver | 自动备份已集成")

# ================= 定时采集逻辑 =================
if st.session_state.auto_running and st.session_state.countdown > 0:
    time.sleep(1)
    st.session_state.countdown -= 1
    if st.session_state.countdown == 0:
        with st.spinner("正在执行定时采集所有项目..."):
            projects = pd.read_sql("SELECT * FROM projects", conn)
            for _, row in projects.iterrows():
                amount, supporters, err = get_makuake_data(row['url'])
                if amount is not None:
                    save_history(row['id'], amount, supporters)
        st.session_state.countdown = st.session_state.global_interval
        st.rerun()
    else:
        st.rerun()

# ================= 切换项目时触发滚动 =================
if selected_project is not None:
    current_id = selected_project['id']
    if st.session_state.get("selected_project_id") != current_id:
        st.session_state.scroll_to_top = True
        st.session_state.selected_project_id = current_id
