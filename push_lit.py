import requests
import datetime
import os
import re
import json

# --- 配置区域 ---
KEYWORDS = [
    "soil amino sugar", 
    "soil organic carbon fraction", 
    "soil microbial strategy",
    "soil aggregate"
]
EMAIL = "949238124@qq.com"
MAX_RESULTS_PER_KEYWORD = 5  # 每个关键词只展示5篇
START_YEAR = 2026            # 起始年份

WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK")

def get_date_range(start_year):
    # 起始日期：指定年份的1月1日
    from_date = f"{start_year}-01-01"
    # 结束日期：不设置 until-pub-date，API 默认就是直到今天
    return from_date

def clean_abstract(text):
    if not text:
        return "无摘要"
    if isinstance(text, list):
        text = text[0] if text else ""
    # 去除常见的 JATS XML 标签
    clean = re.sub(r'<jats:p>', '', str(text))
    clean = re.sub(r'</jats:p>', '', clean)
    clean = re.sub(r'<.*?>', '', clean) 
    return clean.strip()

def fetch_crossref(keyword, from_date):
    url = "https://api.crossref.org/works"
    
    # ✅ 修改点：只设置起始日期，不设置结束日期 (默认为今天)
    # 同时保留 language:en 过滤
    # 格式：from-pub-date:YYYY-MM-DD,language:en
    full_filter = f"from-pub-date:{from_date},language:en"
    
    params = {
        "query": keyword,
        "filter": full_filter,
        "sort": "published",      # 按发表日期排序
        "order": "desc",          # 倒序 (最新的在前)
        "rows": MAX_RESULTS_PER_KEYWORD, # 只取前5条
        "mailto": EMAIL
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code != 200:
            print(f"❌ API 请求失败 ({response.status_code})")
            try:
                err_data = response.json()
                if 'message' in err_data:
                    for msg in err_data['message']:
                        print(f"   ⚠️ 错误: {msg.get('message', '')}")
            except:
                pass
            return []

        data = response.json()
        items = data.get("message", {}).get("items", [])
        
        if not items:
            return []

        results = []
        for item in items:
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
        return results
        
    except Exception as e:
        print(f"💥 程序捕获到异常: {e}")
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
                print("✅ 成功推送到飞书 (Text 模式)!")
            else:
                print(f"⚠️ 飞书返回非零状态码: {res_json}")
        else:
            print(f"❌ 推送 HTTP 失败: {resp.status_code}")
            print(f"   响应内容: {resp.text}")
    except Exception as e:
        print(f"❌ 发送网络请求出错: {e}")

def main():
    from_date = get_date_range(START_YEAR)
    print(f"🔍 开始任务 | 时间范围: {from_date} 至今")
    print(f"🌐 语言过滤: 仅英文 (language:en)")
    print(f"🔢 数量限制: 每个关键词最新 {MAX_RESULTS_PER_KEYWORD} 篇")
    
    full_message = f"【文献精选】({START_YEAR}年 - 至今)\n\n"
    has_new_papers = False
    
    for kw in KEYWORDS:
        papers = fetch_crossref(kw, from_date)
        
        if papers:
            print(f"   -> [{kw}] 找到 {len(papers)} 篇")
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
        else:
            print(f"   -> [{kw}] 无结果")
    
    if not has_new_papers:
        full_message = f"【文献检索测试】({START_YEAR}年 - 至今)\n\n"
        full_message += "✅ 系统运行正常！\n\n"
        full_message += f"⚠️ 自 {START_YEAR} 年以来，Crossref 未收录匹配以下关键词的英文文献（或暂无数据）：\n"
        for kw in KEYWORDS:
            full_message += f"- {kw}\n"
        full_message += "\n💡 请检查关键词拼写或时间范围。"
    
    print("\n--- 准备发送的内容预览 ---")
    print(full_message[:600] + ("..." if len(full_message)>600 else ""))
    print("--------------------------\n")
    
    send_to_feishu(full_message)

if __name__ == "__main__":
    main()
