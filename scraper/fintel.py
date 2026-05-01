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
        # 用于存储不同页面的标签页句柄
        self.tab_map = {} # {url: handle}

    def start_browser(self, urls):
        """初始化浏览器并为每个 URL 打开一个永久标签页"""
        if self.driver:
            return
        
        logger.info(f"正在启动 Fintel 多标签浏览器...")
        options = uc.ChromeOptions()
        options.add_argument("--start-minimized")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")
        
        if not self.visible:
            options.add_argument("--window-size=1440,1080")
            options.add_argument("--window-position=-2000,-2000")
            
        options.add_argument(f"--user-data-dir={config.PROFILE_DIR}")
        
        try:
            self.driver = uc.Chrome(options=options, version_main=147, headless=False)
            
            # 1. 确保登录 (在第一个标签页)
            self._ensure_logged_in()
            
            # 2. 为每个 URL 创建并保存标签页
            for i, url in enumerate(urls):
                if i == 0:
                    self.driver.get(url)
                    self.tab_map[url] = self.driver.current_window_handle
                else:
                    # 使用 Selenium 4 的新窗口/标签页功能
                    self.driver.switch_to.new_window('tab')
                    self.driver.get(url)
                    self.tab_map[url] = self.driver.current_window_handle
                
                logger.info(f"标签页已就绪: {url}")
                time.sleep(2)
                
        except Exception as e:
            logger.error(f"多标签浏览器启动失败: {e}")
            self.stop_browser()
            raise

    def stop_browser(self):
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.tab_map = {}
            logger.info("浏览器已关闭。")

    def _ensure_logged_in(self):
        self.driver.get("https://fintel.io/d")
        time.sleep(5)
        if "/d" not in self.driver.current_url and "/search" not in self.driver.current_url:
            logger.info("🔑 需要重新登录...")
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
                time.sleep(15)
            except Exception as e:
                logger.error(f"自动登录异常: {e}")

    def _clean_security_name(self, val):
        if pd.isna(val): return "Unknown"
        return str(val).split('  ')[0].strip()

    def scrape_from_tab_no_refresh(self, url):
        """仅读取当前标签页内容，不进行刷新（适用于实时推流页面）"""
        if not self.driver or url not in self.tab_map:
            return None
            
        try:
            self.driver.switch_to.window(self.tab_map[url])
            logger.info(f"⚡️ 正在提取实时流数据: {url}")
            
            # 直接获取当前源码，不等待刷新
            html = self.driver.page_source
            tables = pd.read_html(StringIO(html))
            
            if tables:
                df = None
                target_col = None
                for t in tables:
                    for col in ['Ticker', 'Symbol', 'Security', 'symbol', 'ticker']:
                        if col in t.columns:
                            df = t.copy()
                            target_col = col
                            break
                    if df is not None: break
                
                if df is not None:
                    if target_col != 'Security':
                        df['Security'] = df[target_col]
                    df['Security'] = df['Security'].apply(self._clean_security_name)
                    return df
            return None
        except Exception as e:
            logger.error(f"实时流提取失败 ({url}): {e}")
            return None

    def scrape_from_tab(self, url):
        """切换到对应的标签页，刷新并抓取数据"""
        if not self.driver or url not in self.tab_map:
            logger.error(f"标签页不存在或浏览器未启动: {url}")
            return None
            
        try:
            self.driver.switch_to.window(self.tab_map[url])
            logger.info(f"🔄 正在刷新并抓取: {url}")
            
            # 使用 JavaScript 进行刷新，通常比 driver.refresh() 更安静，不易抢夺焦点
            self.driver.execute_script("location.reload();")
            
            wait = WebDriverWait(self.driver, 30)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
            time.sleep(8) 
            
            html = self.driver.page_source
            tables = pd.read_html(StringIO(html))
            
            if tables:
                df = None
                target_col = None
                # 寻找包含 Ticker 信息的列
                for t in tables:
                    for col in ['Ticker', 'Symbol', 'Security', 'symbol', 'ticker']:
                        if col in t.columns:
                            df = t.copy()
                            target_col = col
                            break
                    if df is not None: break
                
                if df is not None:
                    # 统一将 Ticker 列转换为名为 'Security' 的格式，方便后续处理
                    if target_col != 'Security':
                        df['Security'] = df[target_col]
                    
                    df['Security'] = df['Security'].apply(self._clean_security_name)
                    return df
            return None
        except Exception as e:
            logger.error(f"标签页抓取失败 ({url}): {e}")
            return None
