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
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    try:
        print(f"🌐 正在访问: {STREAMLIT_URL}")
        driver.get(STREAMLIT_URL)
        
        wait = WebDriverWait(driver, 30)
        
        try:
            button = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Yes, get this app back up')]"))
            )
            print("✅ 发现唤醒按钮，正在点击...")
            button.click()
            
            wait.until(EC.invisibility_of_element_located(
                (By.XPATH, "//button[contains(text(),'Yes, get this app back up')]")
            ))
            print("🎉 唤醒成功！")
            
            time.sleep(5)
            
        except TimeoutException:
            print("⏰ 未发现唤醒按钮，应用可能已经唤醒。")
            
    except Exception as e:
        print(f"❌ 发生错误: {e}")
    finally:
        driver.quit()
        print("🏁 脚本执行完毕。")

if __name__ == "__main__":
    main()
