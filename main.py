from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException
import os
import time

# 您的Streamlit应用URL（替换成你的实际URL）
STREAMLIT_URL = os.environ.get("STREAMLIT_APP_URL", "https://yuuto-makuake-tracker.streamlit.app/")

def main():
    print("🚀 启动唤醒脚本...")
    
    options = Options()
    options.add_argument('--headless=new')          # 无头模式
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')

    # 初始化驱动（GitHub Actions 环境会自动下载匹配的 ChromeDriver）
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    try:
        print(f"🌐 正在访问: {STREAMLIT_URL}")
        driver.get(STREAMLIT_URL)
        
        # 等待页面加载（最多30秒）
        wait = WebDriverWait(driver, 30)
        
        # 检查是否有唤醒按钮（Streamlit 的休眠页面有一个特定的按钮）
        try:
            # 定位唤醒按钮（根据 Streamlit 的文本内容）
            button = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Yes, get this app back up')]"))
            )
            print("✅ 发现唤醒按钮，正在点击...")
            button.click()
            
            # 等待按钮消失（确认点击成功）
            wait.until(EC.invisibility_of_element_located(
                (By.XPATH, "//button[contains(text(),'Yes, get this app back up')]")
            ))
            print("🎉 唤醒成功！应用已恢复运行。")
            
            # 额外等待几秒让应用完全启动
            time.sleep(5)
            
        except TimeoutException:
            print("⏰ 未发现唤醒按钮，应用可能已经唤醒或无需唤醒。")
            
        # 可选：截图保存（用于调试）
        # driver.save_screenshot("screenshot.png")
        
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        # 这里不退出，让 GitHub Actions 继续执行，避免误判失败
    finally:
        driver.quit()
        print("🏁 脚本执行完毕。")

if __name__ == "__main__":
    main()
