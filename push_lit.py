import requests
import datetime
import os
import re
import json

# --- 🟢 配置区域：在此处自定义你的期刊白名单 ---
# 策略：只要期刊名包含列表中的任意一个字符串，就会被保留。
# 建议：列出土壤学核心期刊的英文名或部分关键词。
TARGET_JOURNALS = [
    "Soil Biology and Biochemistry",
    "Geoderma",
    "Soil Science Society of America Journal",
    "European Journal of Soil Science",
    "Plant and Soil",
    "Soil Research",
    "Journal of Soils and Sediments",
    "Catena",
    "Agriculture, Ecosystems & Environment",
    "Global Change Biology",  # 虽然综合，但土壤碳相关高质量文章多
    "Nature Geoscience",     # 顶级地学
    "Science of the Total Environment",
    "Environmental Science & Technology", # 环境顶刊，含大量土壤研究
    "Biogeochemistry",
    "Soil Use and Management",
    "Applied Soil Ecology",
    "Geophysical Research Letters", # 有时有重要土壤发现
    "Nature Communications", # 综合刊，但需人工筛选，这里先放入
    "PNAS",
    "Global Biogeochemical Cycles"
]

# 如果希望更宽松，可以只写关键词，例如：
# TARGET_JOURNALS = ["Soil", "Geoderma", "Catena", "Biogeochemistry"] 
# 这样只要期刊名里带 "Soil" 的都会通过。

KEYWORDS = [
    "microbial necromass", 
    "mineral-associated organic carbon", 
    "soil microbial community",
    "soil aggregates",
    "soil organic carbon stabilization",
    "soil carbon molecular"
]

EMAIL = "949238124@qq.com"
MAX_RESULTS_PER_KEYWORD = 5
START_YEAR = 2025

WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK")

TODAY = datetime.date.today()
NON_ENGLISH_LANGUAGES = {'zh', 'ja', 'de', 'fr', 'es', 'ru', 'ko', 'pt'}

def get_date_range(start_year):
    return f"{start_year}-01-01"

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
        return True
    if isinstance(languages, list):
        lang_code = languages[0].lower() if languages else ""
    else:
        lang_code = str(languages).lower()
    if lang_code in NON_ENGLISH_LANGUAGES:
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
    if keyword_lower in title_lower:
        return True
    if "-" in keyword_lower:
        if keyword_lower.replace("-", " ") in title_lower:
            return True
    if keyword_lower.endswith("s") and len(keyword_lower) > 3:
        if keyword_lower[:-1] in title_lower:
            return True
    return False

def is_target_journal(journal_name):
    """
    ✅ 核心修改：白名单机制
    检查期刊名是否包含在 TARGET_JOURNALS 列表中
    """
    if not journal_name:
        return False
    
    journal_lower = journal_name.lower()
    
    for target in TARGET_JOURNALS:
        if target.lower() in journal_lower:
            return True
            
    return False

def fetch_crossref(keyword, from_date):
    url = "https://api.crossref.org/works"
    
    # 依然限制为期刊论文，减少噪音
    full_filter = f"from-pub-date:{from_date},type:journal-article"
    
    params = {
        "query.bibliographic": keyword,
        "filter": full_filter,
        "sort": "published",
        "order": "desc",
        "rows": MAX_RESULTS_PER_KEYWORD * 5, # 多取一些，因为白名单过滤可能很严
        "mailto": EMAIL
    }
    
    try:
        print(f"   🔍 正在请求: {keyword} ...")
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code != 200:
            print(f"   ❌ API 请求失败 ({response.status_code})")
            return []

        data = response.json()
        items = data.get("message", {}).get("items", [])
        total_results = data.get("message", {}).get("total-results", 0)
        
        if not items:
            print(f"   ⚠️ 无结果 (总记录数: {total_results})")
            return []

        results = []
        skipped_non_target = 0
        
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
            
            # 3. ✅ 白名单过滤 (最关键的步骤)
            if not is_target_journal(journal):
                skipped_non_target += 1
                # 只在调试时打印前几个被跳过的，避免刷屏
                if skipped_non_target <= 3:
                    print(f"      ⏭️ 跳过非目标期刊: {journal}")
                elif skipped_non_target == 4:
                    print(f"      ... 以及更多非目标期刊被跳过")
                continue
            
            # 4. 标题匹配度检查
            if not title_matches_keyword(title, keyword):
                continue 
            
            # 5. 日期有效性检查
            pub_date_parts = item.get("published", {}).get("date-parts", [[0,0,0]])[0]
            try:
                y = pub_date_parts[0]
                m = pub_date_parts[1] if len(pub_date_parts) > 1 else 1
                d = pub_date_parts[2] if len(pub_date_parts) > 2 else 1
                pub_date_str = f"{y}-{m:02d}-{d:02d}"
                
                if is_future_date(pub_date_str):
                    continue
                    
            except:
                continue
            
            # 6. 提取其他信息
            abstract_raw = item.get("abstract", "")
            abstract = clean_abstract(abstract_raw)
            doi = item.get("DOI", "No DOI")
            
            authors = item.get("author", [])
            author_str = "Unknown Authors"
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
        
        print(f"   ✅ 最终保留 {len(results)} 篇 (跳过非目标期刊: {skipped_non_target})")
        return results
        
    except Exception as e:
        print(f"   💥 程序异常: {e}")
        return []

def send_to_feishu(text_content):
    if not WEBHOOK_URL:
        print("❌ 严重错误: 未找到 FEISHU_WEBHOOK 环境变量！")
        # 即使没有 webhook，也在本地打印出来方便调试
        print("--- 本地模拟输出 ---")
        print(text_content)
        return

    payload = {
        "msg_type": "text",
        "content": {
            "text": text_content
        }
    }
    
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code == 200:
            res_json = resp.json()
            if res_json.get("StatusCode") == 0 or res_json.get("code") == 0:
                print("✅ 成功推送到飞书!")
            else:
                print(f"⚠️ 飞书返回非零状态码: {res_json}")
        else:
            print(f"❌ 推送 HTTP 失败: {resp.status_code}")
            print(resp.text)
    except Exception as e:
        print(f"❌ 发送网络请求出错: {e}")

def main():
    # 启动通知
    if WEBHOOK_URL:
        try:
            start_msg = f"🤖 土壤文献机器人启动\n时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n策略：仅推送指定期刊集"
            requests.post(WEBHOOK_URL, json={"msg_type": "text", "content": {"text": start_msg}}, timeout=5)
        except:
            pass

    from_date = get_date_range(START_YEAR)
    print(f"🚀 开始任务 | 时间范围: {from_date} 至今")
    print(f"📚 目标期刊集数量: {len(TARGET_JOURNALS)}")
    
    full_message = f"【土壤学核心文献推送】({START_YEAR}年 - 至今)\n\n"
    full_message += f"🎯 仅限期刊：{', '.join(TARGET_JOURNALS[:5])} 等 {len(TARGET_JOURNALS)} 本核心期刊\n\n"
    
    has_new_papers = False
    
    for kw in KEYWORDS:
        papers = fetch_crossref(kw, from_date)
        
        if papers:
            has_new_papers = True
            full_message += f"🔬 关键词：{kw}\n"
            full_message += "-" * 30 + "\n"
            for i, p in enumerate(papers, 1):
                short_abstract = p['abstract'][:200] + "..." if len(p['abstract']) > 200 else p['abstract']
                
                full_message += f"{i}. {p['title']}\n"
                full_message += f"   👤 {p['authors']}\n"
                full_message += f"   📖 {p['journal']} | 📅 {p['date']}\n"
                full_message += f"   📝 {short_abstract}\n"
                full_message += f"   🔗 https://doi.org/{p['doi']}\n\n"
            full_message += "\n"
    
    if not has_new_papers:
        full_message += "⚠️ 今日未在目标期刊集中找到符合关键词的最新文献。\n"
        full_message += "💡 可能是近期无新发文，或关键词过于具体。\n"
    
    print("\n--- 最终消息预览 ---")
    print(full_message[:500] + ("..." if len(full_message)>500 else ""))
    
    send_to_feishu(full_message)

if __name__ == "__main__":
    main()




