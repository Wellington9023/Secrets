import os
import requests
import re
import time
import html
from datetime import datetime, timedelta

# =================配置区域=================

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")

# ⚠️【重要安全锁】
# 如果你的服务器时间准确，这里填 None 即可自动获取。
# 如果服务器时间穿越了（比如变成了2026年），请在这里填入真实的年份作为“校准基准”。
# 程序会自动对比：如果系统年份 > 校准年份，则强制使用校准年份的当天。
CALIBRATION_YEAR = 2026 # <--- 设置为当前的真实年份 (例如 2024 或 2025)

USER_AGENT_EMAIL = "kaikaimin@163.com" 

KEYWORDS = [
    "mineral-associated", 
    "necromass", 
    "microbial",
    "strategy",
    "aggregates",
    "MAOC", 
    "POC",
    "CUE",
    "molecular"
]

TARGET_JOURNALS = [
    "Soil Biology and Biochemistry",
    "Soil Biol. Biochem.",
    "Geoderma",
    "Soil Science Society of America Journal",
    "Soil Sci. Soc. Am. J.",
    "European Journal of Soil Science",
    "Eur. J. Soil Sci.",
    "Plant and Soil",
    "Soil Research",
    "Journal of Soils and Sediments",
    "J. Soils Sediments",
    "Catena",
    "Agriculture, Ecosystems & Environment",
    "Agric. Ecosyst. Environ.",
    "Global Change Biology",
    "Sci. Total Environ.",
    "Science of the Total Environment",
    "Environmental Science & Technology",
    "Environ. Sci. Technol.",
    "Biogeochemistry",
    "Soil Use and Management",
    "Applied Soil Ecology",
    "Appl. Soil Ecol.",
    "Nature Geoscience",
    "Nat. Geosci.",
    "Global Biogeochemical Cycles",
    "Glob. Biogeochem. Cycles",
    "Nature Communications",
    "Nat. Commun.",
    "PNAS",
    "Proc. Natl. Acad. Sci. U.S.A.",
    "Geophysical Research Letters",
    "Geophys. Res. Lett.",
    "Vadose Zone Journal",
    "Land Degradation & Development",
    "Land Degradation",
    "Biology and Fertility of Soils",
    "Biol. Fertil. Soils"
]

MAX_PER_KEYWORD = 5
FETCH_LIMIT = MAX_PER_KEYWORD * 10 

# =================工具函数=================

def get_safe_today():
    """
    获取安全的‘今天’日期。
    如果系统时间穿越到未来（超过 CALIBRATION_YEAR），则强制修正为 CALIBRATION_YEAR 的今天。
    """
    now = datetime.now()
    
    # 如果设置了校准年份，且系统年份大于校准年份，说明时间穿越了
    if CALIBRATION_YEAR and now.year > CALIBRATION_YEAR:
        print(f"⚠️ 检测到系统时间穿越 (当前: {now.year}年)，强制校准至 {CALIBRATION_YEAR}年...")
        # 构造一个时间：年份=校准年份，月日=当前系统时间的月日
        # 注意：如果系统是 2026-02-30 (非法日期)，这里可能会报错，所以直接用校准年份的今天
        # 更稳妥的做法：直接使用校准年份的当前真实日期（如果你知道今天是几月几号）
        # 但既然我们不知道今天的真实月日（因为代码是自动跑的），我们假设月日是正确的，只改年份
        try:
            safe_date = now.replace(year=CALIBRATION_YEAR)
        except ValueError:
            # 处理闰年问题 (如系统是2026-02-29，但2025不是闰年)
            safe_date = now.replace(year=CALIBRATION_YEAR, day=28)
        
        print(f"✅ 时间已校准为: {safe_date.strftime('%Y-%m-%d')}")
        return safe_date
    
    # 如果时间正常，直接返回
    print(f"✅ 系统时间正常 ({now.year}年)，直接使用。")
    return now

def clean_abstract(abstract_html):
    if not abstract_html:
        return ""
    text = html.unescape(abstract_html)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def matches_keyword(text, keyword):
    """
    严格匹配：仅匹配关键词本身及其连字符/空格变体。
    """
    if not text:
        return False
    t_lower = text.lower()
    k_lower = keyword.lower()
    
    if k_lower in t_lower:
        return True
    if "-" in k_lower and k_lower.replace("-", " ") in t_lower:
        return True
    if " " in k_lower and k_lower.replace(" ", "-") in t_lower:
        return True
        
    return False

def is_target_journal(journal_name):
    if not TARGET_JOURNALS or not journal_name:
        return bool(TARGET_JOURNALS)
    journal_lower = journal_name.lower()
    for target in TARGET_JOURNALS:
        if target.lower() in journal_lower:
            return True
    return False

def fetch_crossref(keyword):
    url = "https://api.crossref.org/works"
    
    params = {
        "query.bibliographic": keyword,
        "sort": "published",
        "order": "desc",
        "rows": FETCH_LIMIT
    }
    
    headers = {
        "User-Agent": f"LiteratureBot/1.0 (mailto:{USER_AGENT_EMAIL})",
        "Accept": "application/json"
    }

    print(f"🌐 请求: '{keyword}' (获取最新 {FETCH_LIMIT} 条，本地过滤)")
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        
        if response.status_code == 400:
            print(f"   ❌ API 返回 400，尝试无参数降级...")
            fallback_params = {
                "query.bibliographic": keyword,
                "rows": FETCH_LIMIT
            }
            response = requests.get(url


