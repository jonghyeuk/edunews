# Firebase Functions - 입시뉴스 크롤링 시스템
import functions_framework
from firebase_admin import initialize_app, firestore
import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime, timedelta
import logging

# Firebase Admin 초기화
initialize_app()

# 교육청 크롤링 설정
EDUCATION_OFFICES = {
    "교육부": {
        "url": "https://www.moe.go.kr/boardCnts/list.do?boardID=294",
        "selector": ".board-list-table tbody tr",
        "title_selector": ".title a",
        "date_selector": ".date"
    },
    "서울시교육청": {
        "url": "https://www.sen.go.kr/web/services/bbs/bbsList.action?bbsBean.bbsCd=140", 
        "selector": ".bbs-list tbody tr",
        "title_selector": ".subject a",
        "date_selector": ".reg-date"
    },
    "경기도교육청": {
        "url": "https://www.goe.go.kr/home/bbs/bbsList.do?menuNo=1020408",
        "selector": ".board_list tbody tr",
        "title_selector": ".title a", 
        "date_selector": ".date"
    },
    "인천시교육청": {
        "url": "https://www.ice.go.kr/contents.do?menuNo=200047",
        "selector": ".list tbody tr",
        "title_selector": ".subject a",
        "date_selector": ".date"
    }
}

@functions_framework.cloud_event
def weekly_news_crawler(cloud_event):
    """매주 실행되는 뉴스 크롤링 함수"""
    logging.info("🚀 주간 뉴스 크롤링 시작")
    
    try:
        # Firestore 클라이언트
        db = firestore.client()
        
        all_articles = []
        
        # 각 교육청 크롤링
        for office_name, config in EDUCATION_OFFICES.items():
            try:
                articles = crawl_education_office(office_name, config)
                all_articles.extend(articles)
                logging.info(f"✅ {office_name}: {len(articles)}개 기사 수집")
            except Exception as e:
                logging.error(f"❌ {office_name} 크롤링 실패: {str(e)}")
                continue
        
        # 수집된 기사들을 Firestore에 저장
        if all_articles:
            save_articles_to_firestore(db, all_articles)
            logging.info(f"💾 총 {len(all_articles)}개 기사 저장 완료")
        
        return {
            "status": "success",
            "articles_count": len(all_articles),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logging.error(f"❌ 크롤링 시스템 오류: {str(e)}")
        return {
            "status": "error", 
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def crawl_education_office(office_name, config):
    """개별 교육청 웹사이트 크롤링"""
    articles = []
    
    try:
        # 헤더 설정 (봇 차단 방지)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        # 웹페이지 요청
        response = requests.get(config["url"], headers=headers, timeout=10)
        response.raise_for_status()
        response.encoding = 'utf-8'
        
        # HTML 파싱
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 게시글 목록 추출
        article_elements = soup.select(config["selector"])
        
        for element in article_elements[:5]:  # 최신 5개만
            try:
                # 제목 추출
                title_element = element.select_one(config["title_selector"])
                if not title_element:
                    continue
                    
                title = title_element.get_text().strip()
                
                # 링크 추출
                link = title_element.get('href', '')
                if link and not link.startswith('http'):
                    # 상대 경로를 절대 경로로 변환
                    base_url = '/'.join(config["url"].split('/')[:3])
                    link = base_url + link
                
                # 날짜 추출
                date_element = element.select_one(config["date_selector"])
                date_text = date_element.get_text().strip() if date_element else ''
                
                # 최근 30일 이내 뉴스만 필터링
                if is_recent_article(date_text):
                    article = {
                        'title': title,
                        'source': office_name,
                        'link': link,
                        'date': date_text,
                        'content': extract_content_summary(title),
                        'category': classify_article(title),
                        'created_at': firestore.SERVER_TIMESTAMP
                    }
                    articles.append(article)
                    
            except Exception as e:
                logging.warning(f"기사 추출 오류 ({office_name}): {str(e)}")
                continue
                
    except Exception as e:
        logging.error(f"{office_name} 크롤링 오류: {str(e)}")
        
    return articles

def is_recent_article(date_text):
    """최근 기사인지 확인 (30일 이내)"""
    try:
        # 다양한 날짜 형식 처리
        date_text = re.sub(r'[^\d\-\.]', '', date_text)
        
        # 날짜 파싱 시도
        for fmt in ['%Y-%m-%d', '%Y.%m.%d', '%m-%d', '%m.%d']:
            try:
                if len(date_text.split('-')) == 2 or len(date_text.split('.')) == 2:
                    date_text = f"{datetime.now().year}-{date_text}"
                
                article_date = datetime.strptime(date_text, fmt)
                thirty_days_ago = datetime.now() - timedelta(days=30)
                return article_date >= thirty_days_ago
            except:
                continue
        
        # 파싱 실패시 최신으로 간주
        return True
        
    except:
        return True

def extract_content_summary(title):
    """제목을 기반으로 내용 요약 생성"""
    # 간단한 키워드 기반 요약 (실제로는 본문 크롤링 + AI 요약)
    keywords = {
        '입시': '대학입시 관련 중요 공지사항입니다.',
        '수능': '대학수학능력시험 관련 안내사항입니다.',
        '전형': '대학 입학전형 변경 또는 안내사항입니다.',
        '모집': '대학 신입생 모집 관련 정보입니다.',
        '원서': '입학원서 접수 관련 안내입니다.',
        '면접': '입학 면접전형 관련 정보입니다.',
        '특목고': '특목고 입학 관련 안내사항입니다.',
        '자사고': '자율형사립고 관련 정보입니다.'
    }
    
    for keyword, summary in keywords.items():
        if keyword in title:
            return summary
    
    return '입시 관련 중요 정보를 확인하시기 바랍니다.'

def classify_article(title):
    """기사 분류"""
    title_lower = title.lower()
    
    if any(word in title_lower for word in ['대입', '수능', '입시', '전형']):
        return 'major_news'
    elif any(word in title_lower for word in ['대학교', '대학']):
        return 'university_news'  
    elif any(word in title_lower for word in ['일정', '모집', '접수', '마감']):
        return 'exam_schedule'
    else:
        return 'education_office_news'

def save_articles_to_firestore(db, articles):
    """Firestore에 기사 저장"""
    batch = db.batch()
    
    for article in articles:
        # 중복 체크 (제목 + 출처 기준)
        existing = db.collection('news')\
            .where('title', '==', article['title'])\
            .where('source', '==', article['source'])\
            .limit(1)\
            .get()
        
        if not existing:
            # 새 기사만 저장
            doc_ref = db.collection('news').document()
            batch.set(doc_ref, article)
    
    batch.commit()

@functions_framework.https
def get_latest_news(request):
    """API: 최신 뉴스 조회"""
    
    # CORS 헤더 설정
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type'
    }
    
    if request.method == 'OPTIONS':
        return ('', 204, headers)
    
    try:
        db = firestore.client()
        
        # 카테고리별 뉴스 조회
        news_data = {
            'major_news': [],
            'education_office_news': [],
            'university_news': [],
            'exam_schedule': []
        }
        
        # 최근 7일 뉴스
        week_ago = datetime.now() - timedelta(days=7)
        
        for category in news_data.keys():
            docs = db.collection('news')\
                .where('category', '==', category)\
                .order_by('created_at', direction=firestore.Query.DESCENDING)\
                .limit(5)\
                .stream()
            
            for doc in docs:
                news_data[category].append(doc.to_dict())
        
        return (json.dumps(news_data, ensure_ascii=False), 200, headers)
        
    except Exception as e:
        logging.error(f"뉴스 조회 오류: {str(e)}")
        return (json.dumps({'error': str(e)}, ensure_ascii=False), 500, headers)

@functions_framework.https  
def manual_crawl(request):
    """수동 크롤링 트리거 (테스트용)"""
    
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type'
    }
    
    if request.method == 'OPTIONS':
        return ('', 204, headers)
    
    try:
        # 가짜 클라우드 이벤트 생성하여 크롤링 실행
        fake_event = type('CloudEvent', (), {})()
        result = weekly_news_crawler(fake_event)
        
        return (json.dumps(result, ensure_ascii=False), 200, headers)
        
    except Exception as e:
        logging.error(f"수동 크롤링 오류: {str(e)}")
        return (json.dumps({'error': str(e)}, ensure_ascii=False), 500, headers)
