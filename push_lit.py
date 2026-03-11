import requests
import datetime
import os
import re
import time

# --- 🟢 配置区域 ---
# 策略：包含即匹配。建议同时写上“全称”和“常见缩写”。
TARGET_JOURNALS = [
    "Soil Biology and Biochemistry",
    "Soil Biol. Biochem.",  # ✅ 重要：加上缩写
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
    "Sci. Total Environ.",   # ✅ 重要：Science of the Total Environment 的缩写
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
    "Biology and Fertility of Soils",
    "Biol. Fertil. Soils"
]

# 关键词列表
KEYWORDS = [
    "mineral-associated", 
    "necromass", 
    "microbial community",
    "strategy",
    "aggregates",
    "MAOC", # ✅ 新增：直接搜缩写，很多文章标题直接用 MAOC
    "POC"
]

EMAIL = "949238124@qq.com"
MAX_RESULTS_PER_KEYWORD = 5
START_YEAR = 2024 # 确保这里是 2024 或 2025

WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK")

TODAY = datetime.date.today()
NON_ENGLISH_LANGUAGES = {'zh', 'ja', 'de', 'fr', 'es', 'ru', 'ko', 'pt'}

def clean_abstract(text):
    if not text:
        return "无摘要"
    if isinstance(text, list):
        text = text[0] if text else ""
    clean = re.sub(r'<jats:p>', '', str(text))
    clean = re.sub(r'</jats:p>', '', clean)
    clean = re.sub(r'<.*?>', '', clean) 
    return clean.strip()

def is_english_item(item):
    languages = item.get("language", [])
    if not languages:
        return True # 没标语言默认英语
    if isinstance(languages, list):
        lang_code = str(languages[0]).lower()
    else:
        lang_code = str(languages).lower()
    # 提取前两个字母
    lang_short = lang_code[:2]
    if lang_short in NON_ENGLISH_LANGUAGES:
        return False
    return True

def is_future_date(date_str):
    try:
        pub_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        return pub_date > TODAY
    except:
        return False

def title_matches_keyword(title, keyword):
    title_lower = title.lower()
    keyword_lower = keyword.lower()
    
    # 1. 直接包含
    if keyword_lower in title_lower:
        return True
    
    # 2. 处理连字符 (e.g., "mineral-associated" -> "mineral associated")
    if "-" in keyword_lower:
        if keyword_lower.replace("-", " ") in title_lower:
            return True
        if keyword_lower.replace("-", "") in title_lower.replace("-", ""):
            return True
            
    # 3. 处理复数 (简单处理)
    if keyword_lower.endswith("s") and len(keyword_lower) > 4:
        if keyword_lower[:-1] in title_lower:
            return True
            
    # 4. 特殊处理：MAOC / POC 缩写匹配全称
    if keyword_lower == "maoc" and "mineral-associated organic carbon" in title_lower:
        return True
    if keyword_lower == "poc" and "particulate organic carbon" in title_lower:
        return True
        
    return False

def is_target_journal(journal_name):
    if not journal_name:
        return False
    journal_lower = journal_name.lower()
    for target in TARGET_JOURNALS:
        if target.lower() in journal_lower:
            return True
    return False

def fetch_crossref(keyword, from_date):
    url = "https://api.crossref.org/works"
    
    # ⚠️ 修改：移除 type:journal-article 限制，防止元数据标记错误导致漏掉
    # 只保留时间过滤
    full_filter = f"from-pub-date:{from_date}"
    
    params = {
        "query.bibliographic": keyword,
        "filter": full_filter,
        "sort": "published",
        "order": "desc",
        "rows": MAX_RESULTS_PER_KEYWORD * 10, # 扩大搜索范围，因为过滤更严了
        "mailto": EMAIL
    }
    
    print(f"\n🔍 开始检索关键词：[{keyword}]")
    try:
        response = requests.get(url, params=params, timeout=20)
        
        if response.status_code != 200:
            print(f"   ❌ API 错误: {response.status_code}")
            return []

        data = response.json()
        items = data.get("message", {}).get("items", [])
        total = data.get("message", {}).get("total-results", 0)
        
        print(f"   📡 API 返回总数: {total} (本次获取前 {len(items)} 条)")
        
        if not items:
            return []

        results = []
        skipped_journal = 0
        skipped_title = 0
        debug_journals = set()
        debug_titles = [] # 记录因期刊不符但标题高度相关的文章

        for item in items:
            # 1. 语言过滤
            if not is_english_item(item):
                continue
            
            # 2. 获取基本信息
            title_list = item.get("title", [])
            if not title_list:
                continue
            title = title_list[0]
            
            journal_list = item.get("container-title", [])
            journal = journal_list[0] if journal_list else "Unknown Journal"
            
            # 3. 日期检查
            pub_date_parts = item.get("published", {}).get("date-parts", [[0,0,0]])[0]
            try:
                y = int(pub_date_parts[0])
                m = int(pub_date_parts[1]) if len(pub_date_parts) > 1 else 1
                d = int(pub_date_parts[2]) if len(pub_date_parts) > 2 else 1
                pub_date_str = f"{y}-{m:02d}-{d:02d}"
                if is_future_date(pub_date_str):
                    continue
            except Exception as e:
                continue # 日期解析失败跳过

            # 4. 标题匹配检查 (先检查标题，因为标题不匹配就没必要看期刊了)
            if not title_matches_keyword(title, keyword):
                skipped_title += 1
                continue 
            
            # 5. ✅ 期刊白名单检查
            if not is_target_journal(journal):
                skipped_journal += 1
                if skipped_journal <= 5:
                    debug_journals.add(journal)
                # 记录“漏网之鱼”：标题匹配但期刊不在白名单
                if len(debug_titles) < 3:
                    debug_titles.append(f"[{journal}] {title[:60]}...")
                continue
            
            # 6. 提取详细信息
            abstract_raw = item.get("abstract", "")
            abstract = clean_abstract(abstract_raw)
            doi = item.get("DOI", "No DOI")
            
            authors = item.get("author", [])
            author_str = "Unknown"
            if authors:
                names = []
                for a in authors[:3]:
                    given = a.get('given', '')
                    family = a.get('family', '')
                    names.append(f"{given} {family}".strip())
                author_str = ", ".join(names)
                if len(authors) > 3:
                    author_str += " et al."
            
            results.append({
                "title": title,
                "abstract": abstract,
                "doi": doi,
                "journal": journal,
                "date": pub_date_str,
                "authors": author_str
            })
            
            if len(results) >= MAX_RESULTS_PER_KEYWORD:
                break
        
        # 📊 打印详细统计
        print(f"   ✅ 成功匹配: {len(results)} 篇")
        print(f"   ⏭️ 因标题不匹配跳过: {skipped_title}")
        print(f"   ⏭️ 因期刊不在白名单跳过: {skipped_journal}")
        
        if skipped_journal > 0:
            print(f"   💡 [提示] 以下期刊被拦截，如需收录请加入 TARGET_JOURNALS:")
            for j in list(debug_journals)[:5]:
                print(f"      - \"{j}\"")
        
        if debug_titles:
            print(f"   👀 [漏网之鱼] 标题匹配但期刊未收录的例子:")
            for t in debug_titles:
                print(f"      - {t}")

        return results
        
    except Exception as e:
        print(f"   💥 发生异常: {e}")
        return []

def send_to_feishu(text_content):
    if not WEBHOOK_URL:
        print("\n⚠️ 未检测到 FEISHU_WEBHOOK，仅在本地输出:")
        print(text_content)
        return

    payload = {"msg_type": "text", "content": {"text": text_content}}
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code == 200:
            print("✅ 飞书推送成功!")
        else:
            print(f"❌ 飞书推送失败: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"❌ 网络错误: {e}")

def main():
    print(f"🤖 启动土壤文献机器人 | 时间: {datetime.datetime.now()}")
    print(f"🎯 目标期刊库大小: {len(TARGET_JOURNALS)}")
    
    from_date = f"{START_YEAR}-01-01"
    full_message = f"【土壤学核心文献推送】({START_YEAR}年 - 至今)\n\n"
    full_message += f"📚 覆盖期刊：{len(TARGET_JOURNALS)} 本核心期刊\n\n"
    
    has_papers = False
    
    for kw in KEYWORDS:
        papers = fetch_crossref(kw, from_date)
        if papers:
            has_papers = True
            full_message += f"🔬 关键词：{kw}\n" + "-"*30 + "\n"
            for i, p in enumerate(papers, 1):
                abs_short = p['abstract'][:150] + "..." if len(p['abstract']) > 150 else p['abstract']
                full_message += f"{i}. {p['title']}\n"
                full_message += f"   👤 {p['authors']} | 📅 {p['date']}\n"
                full_message += f"   📖 {p['journal']}\n"
                full_message += f"   📝 {abs_short}\n"
                full_message += f"   🔗 https://doi.org/{p['doi']}\n\n"
    
    if not has_papers:
        full_message += "⚠️ 本次未在指定期刊中找到最新文献。\n"
        full_message += "💡 请检查日志中的 [漏网之鱼] 和 [提示] 部分，可能需要扩充期刊白名单。\n"
    
    print("\n" + "="*30)
    print(full_message)
    print("="*30)
    
    send_to_feishu(full_message)

if __name__ == "__main__":
    main()
