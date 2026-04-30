import os
import time
import pandas as pd
from io import StringIO
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from utils.config import config

class FintelScraper:
    def __init__(self, visible=False):
        self.visible = visible
        self.driver = None

    def _get_driver(self):
        options = uc.ChromeOptions()
        if self.visible:
            options.add_argument("--window-size=1280,1024")
            options.add_argument("--window-position=100,100")
        else:
            options.add_argument("--window-size=1440,1080")
            options.add_argument("--window-position=-2000,-2000")
            
        options.add_argument(f"--user-data-dir={config.PROFILE_DIR}")
        return uc.Chrome(options=options, version_main=147, headless=False)

    def _clean_security_name(self, val):
        if pd.isna(val): return "Unknown"
        return str(val).split('  ')[0].strip()

    def run(self, url="https://fintel.io/shortSqueeze"):
        print(f"🚀 启动 Fintel 抓取引擎 (目标: {url})...")
        self.driver = self._get_driver()
        wait = WebDriverWait(self.driver, 30)
        
        try:
            # 1. 检查 Session
            self.driver.get("https://fintel.io/d")
            time.sleep(5)
            
            if "/d" not in self.driver.current_url and "/search" not in self.driver.current_url:
                print("🔑 Session 失效，尝试登录...")
                self.driver.get("https://fintel.io/login")
                try:
                    email = wait.until(EC.element_to_be_clickable((By.NAME, "email")))
                    self.driver.execute_script("arguments[0].value = arguments[1];", email, config.FINTEL_USER)
                    pwd = self.driver.find_element(By.NAME, "password")
                    self.driver.execute_script("arguments[0].value = arguments[1];", pwd, config.FINTEL_PASS)
                    
                    time.sleep(2)
                    submit = self.driver.find_element(By.XPATH, "//button[@type='submit']")
                    self.driver.execute_script("arguments[0].click();", submit)
                    time.sleep(10)
                except:
                    pass

            # 2. 抓取目标页面
            self.driver.get(url)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
            time.sleep(8)
            
            html = self.driver.page_source
            tables = pd.read_html(StringIO(html))
            
            if tables:
                df = None
                for t in tables:
                    if any(col in t.columns for col in ['Ticker', 'Symbol', 'Security']):
                        df = t
                        break
                if df is None: df = tables[0]
                
                # 返回全部数据，由机器人逻辑决定排序和切片
                df_all = df.copy()
                df_all['Security'] = df_all['Security'].apply(self._clean_security_name)
                return df_all
            return None

        except Exception as e:
            print(f"❌ 抓取失败: {e}")
            return None
        finally:
            if self.driver:
                self.driver.quit()
