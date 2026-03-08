import requests
import datetime
import os
import re
import json

# --- 配置区域 ---
KEYWORDS = [
    "microbial necromass", 
    "mineral-associated organic carbon", 
    "soil microbial community",
    "soil aggregates"
]
EMAIL = "949238124@qq.com"
MAX_RESULTS_PER_KEYWORD = 5
START_YEAR = 2025  # 建议先设为2024测试数据

WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK")

# ❌ Crossref API 不支持 language 过滤，我们手动排除常见非英文代码
NON_ENGLISH_LANGUAGES = {'zh', 'ja', 'de', 'fr', 'es', 'ru', 'ko', 'pt'}

def get_date_range(start_year):
    from_date = f"{start_year}-01-01"
    return from_date

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
    """
    检查条目是否为英文。
    如果 Crossref 返回了 language 字段，则检查它。
    如果没有返回，默认认为是英文（因为我们的关键词是英文）。
    """
    languages = item.get("language", [])
    if not languages:
        return True  # 没有语言标记，默认通过
    
    # languages 通常是列表，如 ['en'] 或 ['zh']
    if isinstance(languages, list):
        lang_code = languages[0].lower() if languages else ""
    else:
        lang_code = str(languages).lower()
        
    if lang_code in NON_ENGLISH_LANGUAGES:
        return False
    return True

def fetch_crossref(keyword, from_date):
    url = "https://api.crossref.org/works"
    
    # ✅ 修改点：移除了 language:en，因为它会导致 400 错误
    # 只保留日期过滤
    full_filter = f"from-pub-date:{from_date}"
    
    params = {
        "query.bibliographic": keyword,
        "filter": full_filter,
        "sort": "published",
        "order": "desc",
        "rows": MAX_RESULTS_PER_KEYWORD * 2, # 多取一些，以便过滤掉非英文后还够5篇
        "mailto": EMAIL
    }
    
    try:
        print(f"   🔍 正在请求: {keyword} ...")
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code != 200:
            print(f"   ❌ API 请求失败 ({response.status_code})")
            # 打印具体错误信息
            try:
                err_data = response.json()
                msg = err_data.get("message", "")
                if isinstance(msg, list):
                    for m in msg:
                        print(f"      详情: {m.get('message', '')}")
                else:
                    print(f"      详情: {msg}")
            except:
                print(f"      响应内容: {response.text[:200]}")
            return []

        data = response.json()
        items = data.get("message", {}).get("items", [])
        total_results = data.get("message", {}).get("total-results", 0)
        
        if not items:
            print(f"   ⚠️ 无结果 (总记录数: {total_results})")
            return []

        results = []
        for item in items:
            # ✅ 手动过滤非英文
            if not is_english_item(item):
                continue
                
            title_list = item.get("title", [])
            if not title_list:
                continue
            title = title_list[0]
            
            abstract_raw = item.get("abstract", "")
            abstract = clean_abstract(abstract_raw)
            
            doi = item.get("DOI", "No DOI")
            
            journal_list = item.get("container-title", [])
            journal = journal_list[0] if journal_list else "Unknown Journal"
            
            pub_date_parts = item.get("published", {}).get("date-parts", [[0,0,0]])[0]
            try:
                y = pub_date_parts[0]
                m = pub_date_parts[1] if len(pub_date_parts) > 1 else 1
                d = pub_date_parts[2] if len(pub_date_parts) > 2 else 1
                pub_date_str = f"{y}-{m:02d}-{d:02d}"
            except:
                pub_date_str = "Unknown Date"
            
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
            
            # 如果已经收集够5篇，停止
            if len(results) >= MAX_RESULTS_PER_KEYWORD:
                break
        
        print(f"   ✅ 最终保留 {len(results)} 篇英文文献 (总命中: {total_results})")
        return results
        
    except Exception as e:
        print(f"   💥 程序捕获到异常: {e}")
        return []

def send_to_feishu(text_content):
    if not WEBHOOK_URL:
        print("❌ 严重错误: 未找到 FEISHU_WEBHOOK 环境变量！")
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
    except Exception as e:
        print(f"❌ 发送网络请求出错: {e}")

def main():
    from_date = get_date_range(START_YEAR)
    print(f"🚀 开始任务 | 时间范围: {from_date} 至今")
    print(f"🌐 语言策略: 自动过滤非英文 (代码层过滤)")
    print(f"🔢 数量限制: 每个关键词最新 {MAX_RESULTS_PER_KEYWORD} 篇")
    
    full_message = f"【文献精选】({START_YEAR}年 - 至今)\n\n"
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
                full_message += f"   作者：{p['authors']}\n"
                full_message += f"   期刊：{p['journal']} | 日期：{p['date']}\n"
                full_message += f"   摘要：{short_abstract}\n"
                full_message += f"   链接：https://doi.org/{p['doi']}\n\n"
            full_message += "\n"
    
    if not has_new_papers:
        full_message = f"【文献检索提醒】({START_YEAR}年 - 至今)\n\n"
        full_message += "✅ 系统运行正常，API 连接成功。\n\n"
        full_message += f"⚠️ 在 Crossref 中未找到匹配以下关键词的**英文**文献：\n"
        for kw in KEYWORDS:
            full_message += f"- {kw}\n"
        full_message += f"\n💡 建议:\n1. 确认关键词拼写 (如连字符、单复数)。\n2. 尝试扩大时间范围 (当前设为 {START_YEAR} 年)。\n3. 某些细分领域可能近期无新发文。"
    
    print("\n--- 最终消息预览 ---")
    print(full_message[:800] + ("..." if len(full_message)>800 else ""))
    
    send_to_feishu(full_message)

if __name__ == "__main__":
    main()


