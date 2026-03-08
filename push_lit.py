import requests
import datetime
import os
import re
import json

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
    if isinstance(text, list):
        # 有时 abstract 是个列表，取第一个
        text = text[0] if text else ""
    # 去除常见的 JATS XML 标签
    clean = re.sub(r'<jats:p>', '', str(text))
    clean = re.sub(r'</jats:p>', '', clean)
    clean = re.sub(r'<.*?>', '', clean) 
    return clean.strip()

def fetch_crossref(keyword, from_date, until_date):
    url = "https://api.crossref.org/works"
    
    # ✅ 关键修改：彻底移除 select 参数，使用默认返回字段，避免 400 错误
    params = {
        "query": keyword,
        "from-pub-date": from_date,
        "until-pub-date": until_date,
        "sort": "published",
        "order": "desc",
        "rows": MAX_RESULTS_PER_KEYWORD,
        "mailto": EMAIL
        # "select": "..."  <-- 已删除，不再限制返回字段
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        
        # 详细错误处理
        if response.status_code != 200:
            print(f"❌ API 请求失败 ({response.status_code}): {response.url}")
            try:
                err_data = response.json()
                print(f"   错误详情: {err_data}")
            except:
                print(f"   原始响应: {response.text[:200]}")
            return []

        data = response.json()
        items = data.get("message", {}).get("items", [])
        
        results = []
        for item in items:
            title_list = item.get("title", [])
            if not title_list:
                continue
            title = title_list[0]
            
            # 获取摘要 (现在肯定在默认返回里了)
            abstract_raw = item.get("abstract", "")
            abstract = clean_abstract(abstract_raw)
            
            doi = item.get("DOI", "No DOI")
            
            # 安全获取期刊名
            journal_list = item.get("container-title", [])
            journal = journal_list[0] if journal_list else "Unknown Journal"
            
            # 安全获取日期
            pub_date_parts = item.get("published", {}).get("date-parts", [[0,0,0]])[0]
            # 防止日期部分缺失导致 IndexError
            try:
                y = pub_date_parts[0]
                m = pub_date_parts[1] if len(pub_date_parts) > 1 else 1
                d = pub_date_parts[2] if len(pub_date_parts) > 2 else 1
                pub_date_str = f"{y}-{m:02d}-{d:02d}"
            except:
                pub_date_str = "Unknown Date"
            
            # 安全获取作者
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
        return results
        
    except Exception as e:
        print(f"💥 程序捕获到异常: {e}")
        return []

def send_to_feishu(text_content):
    if not WEBHOOK_URL:
        print("❌ 严重错误: 未找到 FEISHU_WEBHOOK 环境变量！")
        print("请检查 GitHub Settings -> Secrets 是否设置了 FEISHU_WEBHOOK")
        print("--- 本地模拟输出 ---")
        print(text_content)
        return

    payload = {
        "msg_type": "markdown",
        "content": {
            "text": text_content
        }
    }
    
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code == 200:
            res_json = resp.json()
            # 飞书成功通常返回 StatusCode: 0
            if res_json.get("StatusCode") == 0 or res_json.get("code") == 0:
                print("✅ 成功推送到飞书!")
            else:
                print(f"⚠️ 飞书返回非零状态码: {res_json}")
        else:
            print(f"❌ 推送 HTTP 失败: {resp.status_code}")
            print(f"   响应内容: {resp.text}")
    except Exception as e:
        print(f"❌ 发送网络请求出错: {e}")

def main():
    from_date, until_date = get_date_range(TIME_RANGE_HOURS)
    print(f"🔍 开始任务 | 时间范围: {from_date} 至 {until_date}")
    print(f"📧 使用邮箱: {EMAIL}")
    
    full_message = f"📅 **文献日报** ({from_date} ~ {until_date})\n\n"
    has_new_papers = False
    
    for kw in KEYWORDS:
        print(f"   -> 正在检索: [{kw}] ...")
        papers = fetch_crossref(kw, from_date, until_date)
        
        if papers:
            print(f"      ✅ 找到 {len(papers)} 篇")
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
        else:
            print(f"      ⚪ 无结果")
    
    # 构造最终消息
    if not has_new_papers:
        full_message = f"📅 **文献日报测试** ({from_date} ~ {until_date})\n\n"
        full_message += f"✅ **系统运行正常！**\n\n"
        full_message += f"⚠️ 过去 {TIME_RANGE_HOURS} 小时内，Crossref 未收录匹配以下关键词的新文献：\n"
        for kw in KEYWORDS:
            full_message += f"- `{kw}`\n"
        full_message += "\n💡 机器人将持续监控，一旦有新文章将立即推送。"
    
    print("\n--- 准备发送的内容预览 ---")
    # 打印前 500 字符预览
    print(full_message[:500] + ("..." if len(full_message)>500 else ""))
    print("--------------------------\n")
    
    send_to_feishu(full_message)

if __name__ == "__main__":
    main()
