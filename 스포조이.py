import re
import ssl
import time
import json
import os
import requests
import urllib3
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 0. 설정 정보
# ==========================================
TELEGRAM_TOKEN = "7713068391:AAFIOAa_olH-FHzrIJsDsgDQXGMZ0FW5PUE"
CHAT_ID = "-5420806624"
CACHE_FILE = "pitcher_cache.json"

# ==========================================
# 1. SSL 레거시 연결 어댑터
# ==========================================
class LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        try:
            ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        except Exception:
            pass
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

# ==========================================
# 2. 캐시(기억) 파일 읽기/쓰기 함수 (날짜 체크 포함)
# ==========================================
def load_cache(today_str):
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 저장된 날짜가 오늘 날짜와 다르면 캐시 초기화 (날짜가 바뀐 경우)
                if data.get("date") == today_str:
                    return data.get("pitchers", {})
        except Exception:
            return {}
    return {}

def save_cache(today_str, pitchers_data):
    try:
        data = {
            "date": today_str,
            "pitchers": pitchers_data
        }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"❌ 캐시 저장 오류: {e}")

# ==========================================
# 3. 스탯 파싱 함수
# ==========================================
def parse_pitcher_info(pitcher_name, raw_season_text="", raw_l10_text=""):
    p_name = pitcher_name.strip() if pitcher_name else "미정"
    
    if not p_name or p_name in ["미정", "-", "없음", ""]:
        return "미정", "선발투수 미정", "선발투수 미정"

    season_pattern = r"(2026)?(\d+)(\d)(\d)(\d)(\d+\.\d)(\d+)(\d+)(\d+)(\d+)(\d+)(\d+)(\d+\.\d+)"
    season_match = re.search(season_pattern, raw_season_text.replace(" ", "")) if raw_season_text else None
    
    l10_pattern = r"10경기(\d)(\d)(\d)(\d+\.\d)(\d+)(\d+)(\d+)(\d+)(\d+)(\d+)(\d+\.\d+)"
    l10_match = re.search(l10_pattern, raw_l10_text.replace(" ", "")) if raw_l10_text else None

    def fmt_season(m):
        if not m: return "2026 시즌 스탯 없음"
        return f"2026시즌: {m.group(2)}경기 {m.group(3)}승 {m.group(4)}패 {m.group(5)}세 | {m.group(6)}이닝 | {m.group(7)}실점 {m.group(8)}자책 | {m.group(9)}피안타 {m.group(10)}피홈런 | {m.group(11)}삼진 {m.group(12)}포볼 | ERA {m.group(13)}"

    def fmt_l10(m):
        if not m: return "최근 10경기 스탯 없음"
        return f"최근 10경기: {m.group(1)}승 {m.group(2)}패 {m.group(3)}세 | {m.group(4)}이닝 | {m.group(5)}실점 {m.group(6)}자책 | {m.group(7)}피안타 {m.group(8)}피홈런 | {m.group(9)}삼진 {m.group(10)}포볼 | ERA {m.group(11)}"

    return p_name, fmt_season(season_match), fmt_l10(l10_match)

# ==========================================
# 4. 텔레그램 전송 함수
# ==========================================
def send_telegram(message):
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        res = requests.post(telegram_url, data=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"❌ 텔레그램 전송 중 오류: {e}")
        return False

# ==========================================
# 5. 모니터링 및 상태 비교 함수
# ==========================================
def check_and_notify_pitchers():
    kst = timezone(timedelta(hours=9))
    today_str = datetime.now(kst).strftime("%Y-%m-%d")
    
    url = "https://www.spojoy.com/baseball/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    session = requests.Session()
    session.mount("https://", LegacySSLAdapter())
    
    known_pitchers = load_cache(today_str)  # 오늘 날짜 기준 캐시 불러오기
    updated = False
    
    try:
        res = session.get(url, headers=headers, verify=False, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, "html.parser")
        
        tables = soup.select("table")
        
        for idx, table in enumerate(tables):
            full_text = table.get_text()
            if "vs" not in full_text and "선발" not in full_text:
                continue
                
            p_matches = re.findall(r"선발\s*[:\s]*([가-힣a-zA-Z]+)", full_text)
            
            away_p = p_matches[0] if len(p_matches) >= 1 else "미정"
            home_p = p_matches[1] if len(p_matches) >= 2 else "미정"
            
            if away_p == "미정" and home_p == "미정":
                continue
                
            game_id = f"GAME_{idx}"
            current_status = [away_p, home_p]
            
            # [상태 1] 최초 선발투수 발표 시 (또는 날짜가 바뀌어 새로 리셋된 경우)
            if game_id not in known_pitchers:
                known_pitchers[game_id] = current_status
                updated = True
                
                away_p_name, away_season, away_l10 = parse_pitcher_info(away_p, full_text, full_text)
                home_p_name, home_season, home_l10 = parse_pitcher_info(home_p, full_text, full_text)
                
                msg = (
                    f"📢 [선발투수 발표 알림 ({today_str})]\n\n"
                    f"• 원정 선발: {away_p_name}\n"
                    f"  - {away_season}\n"
                    f"  - {away_l10}\n\n"
                    f"• 홈 선발: {home_p_name}\n"
                    f"  - {home_season}\n"
                    f"  - {home_l10}\n"
                    f"{'='*35}"
                )
                if send_telegram(msg):
                    print(f"✅ [최초 발표] 텔레그램 전송 완료 ({away_p} vs {home_p})")

            # [상태 2] 기존 선발투수가 변경된 경우
            elif known_pitchers[game_id] != current_status:
                prev_away, prev_home = known_pitchers[game_id]
                known_pitchers[game_id] = current_status
                updated = True
                
                away_p_name, away_season, away_l10 = parse_pitcher_info(away_p, full_text, full_text)
                home_p_name, home_season, home_l10 = parse_pitcher_info(home_p, full_text, full_text)
                
                msg = (
                    f"🔄 [선발투수 변경 알림 ({today_str})]\n"
                    f"⚠️ 이전 선발: {prev_away} vs {prev_home}\n"
                    f"➡️ 변경 선발: {away_p} vs {home_p}\n\n"
                    f"• 원정 선발: {away_p_name}\n"
                    f"  - {away_season}\n"
                    f"  - {away_l10}\n\n"
                    f"• 홈 선발: {home_p_name}\n"
                    f"  - {home_season}\n"
                    f"  - {home_l10}\n"
                    f"{'='*35}"
                )
                if send_telegram(msg):
                    print(f"🔄 [선발 변경 감지] 텔레그램 전송 완료 ({prev_away}vs{prev_home} -> {away_p}vs{home_p})")

            else:
                pass

        if updated:
            save_cache(today_str, known_pitchers)

    except Exception as e:
        print(f"❌ 모니터링 중 오류 발생: {e}")

# ==========================================
# 6. 실행부
# ==========================================
if __name__ == "__main__":
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"[{now_kst}] 선발투수 등록 및 변경 여부 확인 중...")
    check_and_notify_pitchers()
