import requests
import datetime
import os
import re

# --- 配置区域 ---
KEYWORDS = [
    "microbial necromass", 
    "Mineral association organic carbon", 
    "soil microbial community"
]
EMAIL = "949238124@qq.com"
MAX_RESULTS_PER_KEYWORD = 5  # 每个关键词最多推送几篇
TIME_RANGE_HOURS = 48        # 搜索过去 48 小时

# 从 GitHub Secrets 获取 Webhook
WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK")

def get_date_range(hours=48):
    """计算过去 N 小时的日期范围 (YYYY-MM-DD)"""
    now = datetime.datetime.utcnow()
    start_time = now - datetime.timedelta(hours=hours)
    
    # Crossref API 使用 YYYY-MM-DD 格式，不精确到时分秒
    # 为了保险起见，我们取开始日期的当天到结束日期的当天
    # 如果希望更精确，Crossref 也支持，但通常按天过滤足够覆盖 48 小时
    from_date = start_time.strftime("%Y-%m-%d")
    until_date = now.strftime("%Y-%m-%d")
    
    return from_date, until_date

def clean_abstract(text):
    """简单清洗 HTML 标签"""
    if not text:
        return "无摘要"
    # 去除常见的 JATS XML 标签
    clean = re.sub(r'<jats:p>', '', text)
    clean = re.sub(r'</jats:p>', '', clean)
    clean = re.sub(r'<.*?>', '', clean) # 去除其他所有 HTML 标签
    return clean.strip()

def fetch_crossref(keyword, from_date, until_date):
    url = "https://api.crossref.org/works"
    params = {
        "query": keyword,  # 使用 query 搜索标题和摘要，覆盖面更广
        "from-pub-date": from_date,
        "until-pub-date": until_date,
        "sort": "published",
        "order": "desc",
        "rows": MAX_RESULTS_PER_KEYWORD,
        "mailto": EMAIL,
        "select": "title,abstract,DOI,published,container-title,author"
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        items = data.get("message", {}).get("items", [])
        
        results = []
        for item in items:
            title_list = item.get("title", [])
            if not title_list:
                continue
            title = title_list[0]
            
            abstract_raw = item.get("abstract", "")
            abstract = clean_abstract(abstract_raw)
            
            doi = item.get("DOI", "")
            journal_list = item.get("container-title", [])
            journal = journal_list[0] if journal_list else "Unknown Journal"
            
            pub_date_parts = item.get("published", {}).get("date-parts", [[0,0,0]])[0]
            pub_date_str = f"{pub_date_parts[0]}-{pub_date_parts[1]:02d}-{pub_date_parts[2]:02d}"
            
            # 构建作者列表 (只取前3位)
            authors = item.get("author", [])
            author_str = ", ".join([f"{a.get('given', '')} {a.get('family', '')}" for a in authors[:3]])
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
        return results
    except Exception as e:
        print(f"Error fetching {keyword}: {e}")
        return []

def send_to_feishu(text_content):
    if not WEBHOOK_URL:
        print("❌ 未找到 FEISHU_WEBHOOK 环境变量，推送失败。")
        print("--- 模拟输出 ---")
        print(text_content)
        return

    # 飞书 Markdown 消息格式
    payload = {
        "msg_type": "markdown",
        "content": {
            "text": text_content
        }
    }
    
    try:
        resp = requests.post(WEBHOOK_URL, json=payload)
        if resp.status_code == 200:
            print("✅ 成功推送到飞书!")
        else:
            print(f"❌ 推送失败: {resp.status_code}, {resp.text}")
    except Exception as e:
        print(f"❌ 发送请求出错: {e}")

def main():
    from_date, until_date = get_date_range(TIME_RANGE_HOURS)
    print(f"🔍 正在搜索时间范围: {from_date} 至 {until_date}")
    
    full_message = f"📅 **文献日报** ({from_date} ~ {until_date})\n\n"
    has_new_papers = False
    
    for kw in KEYWORDS:
        papers = fetch_crossref(kw, from_date, until_date)
        if papers:
            has_new_papers = True
            full_message += f"🔬 关键词：**{kw}**\n"
            for i, p in enumerate(papers, 1):
                # 截断摘要以防飞书消息过长 (限制在 200 字)
                short_abstract = p['abstract'][:200] + "..." if len(p['abstract']) > 200 else p['abstract']
                
                full_message += f"{i}. **{p['title']}**\n"
                full_message += f"   👤 {p['authors']}\n"
                full_message += f"   📖 {p['journal']} | 📅 {p['date']}\n"
                full_message += f"   📝 {short_abstract}\n"
                full_message += f"   🔗 [DOI](https://doi.org/{p['doi']})\n\n"
            full_message += "---\n\n"
    
    if not has_new_papers:
        full_message = f"📅 **文献日报** ({from_date} ~ {until_date})\n\n😴 过去 {TIME_RANGE_HOURS} 小时内没有发现匹配的新文献。"

    send_to_feishu(full_message)

if __name__ == "__main__":
    main()
