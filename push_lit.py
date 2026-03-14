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
CALIBRATION_YEAR = 2026  # <--- 设置为当前的真实年份 (例如 2024 或 2025)

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
            response = requests.get(url, params=fallback_params, headers=headers, timeout=30)
            
        if response.status_code != 200:
            print(f"   ❌ 请求失败: {response.status_code}")
            return []
            
        data = response.json()
        items = data.get("message", {}).get("items", [])
        total_available = data.get("message", {}).get("total-results", 0)
        
        print(f"   🔍 数据库总数: {total_available}, 本次获取: {len(items)}")
        return items
        
    except Exception as e:
        print(f"   ❌ 网络异常: {e}")
        return []

def process_keyword_data(keyword, items, start_date_obj, end_date_obj):
    valid_articles = []
    seen_dois = set()
    
    for item in items:
        title_list = item.get("title", [])
        title = title_list[0] if title_list else "No Title"
        journal_list = item.get("container-title", [])
        journal = journal_list[0] if journal_list else "Unknown Journal"
        doi = item.get("DOI", "")
        
        if doi in seen_dois: 
            continue
        seen_dois.add(doi)
        
        # --- 本地日期解析与过滤 ---
        pub_date_raw = item.get("published", {}).get("date-parts", [[0,0,0]])
        try:
            p_year = pub_date_raw[0][0]
            p_month = pub_date_raw[0][1] if len(pub_date_raw[0]) > 1 else 1
            p_day = pub_date_raw[0][2] if len(pub_date_raw[0]) > 2 else 1
            
            article_date = datetime(p_year, p_month, p_day)
            
            if article_date < start_date_obj or article_date > end_date_obj:
                continue
                
            pub_date_str = f"{p_year}-{p_month:02d}-{p_day:02d}"
        except Exception:
            # 无法解析日期，标记为未知，但保留（以防是 Online First）
            pub_date_str = "Online First / Date Unknown"

        link = item.get("URL", f"https://doi.org/{doi}")
        abstract_text = clean_abstract(item.get("abstract", ""))
        
        if not is_target_journal(journal):
            continue
            
        if not (matches_keyword(title, keyword) or matches_keyword(abstract_text, keyword)):
            continue
            
        authors = item.get("author", [])
        author_str = "et al."
        if authors:
            first = authors[0].get("given", "")
            last = authors[0].get("family", "")
            author_str = f"{first} {last}" + (" et al." if len(authors) > 1 else "")
        
        match_source = "摘要匹配" if (matches_keyword(abstract_text, keyword) and not matches_keyword(title, keyword)) else "标题匹配"
        
        valid_articles.append({
            "title": title,
            "journal": journal,
            "authors": author_str,
            "date": pub_date_str,
            "link": link,
            "doi": doi,
            "match_source": match_source,
            "abstract_snippet": abstract_text[:150] + "..." if len(abstract_text) > 150 else abstract_text
        })
        
        if len(valid_articles) >= MAX_PER_KEYWORD:
            break
            
    print(f"   ✅ 筛选后: {len(valid_articles)} 篇")
    return valid_articles

def send_combined_message(all_results, start_date, end_date):
    if not FEISHU_WEBHOOK:
        print("⚠️ 未配置 Webhook")
        return

    total_count = sum(len(arts) for kw, arts in all_results.items() if kw != '_meta')
    
    if total_count == 0:
        print("💤 无新文献，不发送消息。")
        return

    content_lines = [
        f"🔬 **土壤碳循环新文献日报**",
        f"📅 检索窗口: {start_date} 至 {end_date}",
        f"📊 共检索 {len(KEYWORDS)} 个关键词，发现 **{total_count}** 篇好文：\n"
    ]

    for kw, articles in all_results.items():
        if kw == '_meta': continue
        if not articles:
            continue
        
        content_lines.append(f"▌ **关键词：{kw}** ({len(articles)}篇)")
        
        for i, art in enumerate(articles, 1):
            icon = "🏷️" if art['match_source'] == "标题匹配" else "📝"
            content_lines.append(
                f"{i}. {icon} **{art['title']}**\n"
                f"   👤 {art['authors']} | 📅 {art['date']}\n"
                f"   📚 {art['journal']}\n"
                f"   🔗 [DOI]({art['link']})\n"
                f"   💡 _{art['abstract_snippet']}_\n"
            )
        content_lines.append("---\n")

    full_text = "\n".join(content_lines)
    
    if len(full_text) > 4000:
        full_text = full_text[:3900] + "\n\n... (内容过长，部分文献未显示)"

    payload = {
        "msg_type": "text",
        "content": {"text": full_text}
    }
    
    try:
        resp = requests.post(FEISHU_WEBHOOK, json=payload)
        if resp.status_code == 200:
            print(f"🚀 成功发送合并消息 (共 {total_count} 篇)!")
        else:
            print(f"❌ 推送失败: {resp.text}")
    except Exception as e:
        print(f"❌ 发送异常: {e}")

def main():
    print(f"🚀 启动任务")
    
    # 1. 获取安全的“今天”
    real_end = get_safe_today()
    real_start = real_end - timedelta(days=14)
    
    start_str = real_start.strftime("%Y-%m-%d")
    end_str = real_end.strftime("%Y-%m-%d")
    
    print(f"📅 设定检索范围: {start_str} 到 {end_str}")
    
    all_results = {'_meta': {'start': start_str, 'end': end_str}}
    
    for kw in KEYWORDS:
        print(f"\n>>> 处理关键词: [{kw}]")
        items = fetch_crossref(kw)
        articles = process_keyword_data(kw, items, real_start, real_end)
        all_results[kw] = articles
        time.sleep(1)

    print("\n" + "="*30)
    print("📦 正在生成合并报告...")
    send_combined_message(all_results, start_str, end_str)
    print("🎉 任务结束")

if __name__ == "__main__":
    main()
