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
MAX_RESULTS_PER_KEYWORD = 5
TIME_RANGE_HOURS = 48

WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK")

def get_date_range(hours=48):
    now = datetime.datetime.utcnow()
    start_time = now - datetime.timedelta(hours=hours)
    from_date = start_time.strftime("%Y-%m-%d")
    until_date = now.strftime("%Y-%m-%d")
    return from_date, until_date

def clean_abstract(text):
    if not text:
        return "无摘要"
    clean = re.sub(r'<jats:p>', '', text)
    clean = re.sub(r'</jats:p>', '', clean)
    clean = re.sub(r'<.*?>', '', clean)
    return clean.strip()

def fetch_crossref(keyword, from_date, until_date):
    url = "https://api.crossref.org/works"
    params = {
        "query": keyword,
        "from-pub-date": from_date,
        "until-pub-date": until_date,
        "sort": "published",
        "order": "desc",
        "rows": MAX_RESULTS_PER_KEYWORD,
        "mailto": EMAIL,
        # ✅ 修复点：移除了 abstract，防止 400 错误
        "select": "title,DOI,published,container-title,author" 
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status() # 如果这里还报错，那就是其他问题
        data = response.json()
        items = data.get("message", {}).get("items", [])
        
        results = []
        for item in items:
            title_list = item.get("title", [])
            if not title_list:
                continue
            title = title_list[0]
            
            # 即使 select 没选 abstract，默认返回的数据里通常也包含它
            # 如果某些条目真的没有，get 方法会返回 None，clean_abstract 会处理
            abstract_raw = item.get("abstract", "")
            abstract = clean_abstract(abstract_raw)
            
            doi = item.get("DOI", "")
            journal_list = item.get("container-title", [])
            journal = journal_list[0] if journal_list else "Unknown Journal"
            
            pub_date_parts = item.get("published", {}).get("date-parts", [[0,0,0]])[0]
            pub_date_str = f"{pub_date_parts[0]}-{pub_date_parts[1]:02d}-{pub_date_parts[2]:02d}"
            
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
        print("❌ 未找到 FEISHU_WEBHOOK 环境变量。")
        print("--- 模拟输出 ---")
        print(text_content)
        return

    payload = {
        "msg_type": "markdown",
        "content": {
            "text": text_content
        }
    }
    
    try:
        resp = requests.post(WEBHOOK_URL, json=payload)
        if resp.status_code == 200:
            # 飞书成功返回通常是 {"StatusCode":0,"StatusMessage":"success"} 或类似
            # 但 requests 只要状态码是 200 就认为成功
            print("✅ 成功推送到飞书!")
        else:
            print(f"❌ 推送失败: {resp.status_code}, Response: {resp.text}")
    except Exception as e:
        print(f"❌ 发送请求出错: {e}")

def main():
    from_date, until_date = get_date_range(TIME_RANGE_HOURS)
    print(f"🔍 正在搜索时间范围: {from_date} 至 {until_date}")
    
    full_message = f"📅 **文献日报** ({from_date} ~ {until_date})\n\n"
    has_new_papers = False
    
    for kw in KEYWORDS:
        print(f"   -> 检索关键词: {kw}")
        papers = fetch_crossref(kw, from_date, until_date)
        if papers:
            has_new_papers = True
            full_message += f"🔬 关键词：**{kw}**\n"
            for i, p in enumerate(papers, 1):
                short_abstract = p['abstract'][:200] + "..." if len(p['abstract']) > 200 else p['abstract']
                
                full_message += f"{i}. **{p['title']}**\n"
                full_message += f"   👤 {p['authors']}\n"
                full_message += f"   📖 {p['journal']} | 📅 {p['date']}\n"
                full_message += f"   📝 {short_abstract}\n"
                full_message += f"   🔗 [DOI](https://doi.org/{p['doi']})\n\n"
            full_message += "---\n\n"
    
    # 调试模式：即使没文章也发消息，方便你确认机器人活着
    if not has_new_papers:
        full_message = f"📅 **文献日报测试** ({from_date} ~ {until_date})\n\n"
        full_message += f"✅ **机器人运行正常！**\n\n"
        full_message += f"⚠️ 过去 {TIME_RANGE_HOURS} 小时内未检索到匹配以下关键词的新文献：\n"
        for kw in KEYWORDS:
            full_message += f"- {kw}\n"
        full_message += "\n💡 一旦有新文章收录，您将立即收到通知。"

    print("--- 准备发送的消息 ---")
    print(full_message)
    print("--------------------")
    
    send_to_feishu(full_message)

if __name__ == "__main__":
    main()
