import os
import time
import logging
import pandas as pd
from io import StringIO
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from utils.config import config

logger = logging.getLogger(__name__)

class FintelScraper:
    def __init__(self, visible=False):
        self.visible = visible
        self.driver = None

    def start_browser(self):
        """初始化并启动浏览器"""
        if self.driver:
            return
        
        logger.info(f"正在启动 Fintel 浏览器 (模式: {'可见' if self.visible else '静默'})...")
        options = uc.ChromeOptions()
        options.add_argument("--start-minimized")
        if self.visible:
            options.add_argument("--window-size=1280,1024")
            options.add_argument("--window-position=100,100")
        else:
            options.add_argument("--window-size=1440,1080")
            options.add_argument("--window-position=-2000,-2000")
            
        options.add_argument(f"--user-data-dir={config.PROFILE_DIR}")
        
        try:
            self.driver = uc.Chrome(options=options, version_main=147, headless=False)
            # 初始检查登录
            self._ensure_logged_in()
        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            raise

    def stop_browser(self):
        """关闭浏览器"""
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("浏览器已关闭。")

    def _ensure_logged_in(self):
        """确保当前浏览器处于登录状态"""
        self.driver.get("https://fintel.io/d")
        time.sleep(5)
        
        if "/d" not in self.driver.current_url and "/search" not in self.driver.current_url:
            logger.info("🔑 Session 已失效，尝试自动登录...")
            self.driver.get("https://fintel.io/login")
            wait = WebDriverWait(self.driver, 30)
            try:
                email = wait.until(EC.element_to_be_clickable((By.NAME, "email")))
                self.driver.execute_script("arguments[0].value = arguments[1];", email, config.FINTEL_USER)
                pwd = self.driver.find_element(By.NAME, "password")
                self.driver.execute_script("arguments[0].value = arguments[1];", pwd, config.FINTEL_PASS)
                
                time.sleep(2)
                submit = self.driver.find_element(By.XPATH, "//button[@type='submit']")
                self.driver.execute_script("arguments[0].click();", submit)
                
                # 等待跳转
                logger.info("等待登录跳转...")
                time.sleep(15)
                if "/d" not in self.driver.current_url and "/search" not in self.driver.current_url:
                    logger.warning("自动登录可能失败，当前 URL: " + self.driver.current_url)
            except Exception as e:
                logger.error(f"登录过程异常: {e}")

    def _clean_security_name(self, val):
        if pd.isna(val): return "Unknown"
        return str(val).split('  ')[0].strip()

    def scrape_url(self, url):
        """在当前浏览器中抓取指定 URL 并返回 DataFrame"""
        if not self.driver:
            self.start_browser()
            
        logger.info(f"📡 正在拉取数据: {url}")
        try:
            self.driver.get(url)
            wait = WebDriverWait(self.driver, 30)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
            time.sleep(8) # 渲染缓冲
            
            html = self.driver.page_source
            tables = pd.read_html(StringIO(html))
            
            if tables:
                df = None
                for t in tables:
                    if any(col in t.columns for col in ['Ticker', 'Symbol', 'Security']):
                        df = t
                        break
                if df is None: df = tables[0]
                
                df_cleaned = df.copy()
                df_cleaned['Security'] = df_cleaned['Security'].apply(self._clean_security_name)
                return df_cleaned
            return None
        except Exception as e:
            logger.error(f"抓取 URL 失败 ({url}): {e}")
            # 如果崩溃了，尝试重置浏览器
            self.stop_browser()
            return None
