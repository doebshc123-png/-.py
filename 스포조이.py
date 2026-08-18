import re
import ssl
import time
import requests
import urllib3
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 0. SSL 레거시 연결 어댑터
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
# 1. 설정 정보
# ==========================================
TELEGRAM_TOKEN = "7713068391:AAFIOAa_olH-FHzrIJsDsgDQXGMZ0FW5PUE"
CHAT_ID = "-5420806624"

# 각 경기별 최근 선발투수 상태 저장 딕셔너리
# 구조: { "경기ID": ("원정선발투수", "홈선발투수") }
KNOWN_PITCHERS = {}

# ==========================================
# 2. 스탯 파싱 함수
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
# 3. 텔레그램 전송 함수
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
# 4. 실시간 모니터링 및 변경 감지 함수
# ==========================================
def check_and_notify_pitchers():
    url = "https://www.spojoy.com/baseball/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    session = requests.Session()
    session.mount("https://", LegacySSLAdapter())
    
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
            
            # 둘 다 미정이면 처리 스킵
            if away_p == "미정" and home_p == "미정":
                continue
                
            # 경기 고유 키 생성 (테이블 순서 기준)
            game_id = f"GAME_{idx}"
            current_status = (away_p, home_p)
            
            # [상태 1] 최초 선발투수 발표 시
            if game_id not in KNOWN_PITCHERS:
                KNOWN_PITCHERS[game_id] = current_status
                
                away_p_name, away_season, away_l10 = parse_pitcher_info(away_p, full_text, full_text)
                home_p_name, home_season, home_l10 = parse_pitcher_info(home_p, full_text, full_text)
                
                msg = (
                    f"📢 [선발투수 발표 알림]\n\n"
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
            elif KNOWN_PITCHERS[game_id] != current_status:
                prev_away, prev_home = KNOWN_PITCHERS[game_id]
                KNOWN_PITCHERS[game_id] = current_status  # 변경된 상태 업데이트
                
                away_p_name, away_season, away_l10 = parse_pitcher_info(away_p, full_text, full_text)
                home_p_name, home_season, home_l10 = parse_pitcher_info(home_p, full_text, full_text)
                
                msg = (
                    f"🔄 [선발투수 변경 알림]\n"
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

            # [상태 3] 선발투수 변동 없음
            else:
                pass  # 동일한 경우 메시지를 보내지 않음

    except Exception as e:
        print(f"❌ 모니터링 중 오류 발생: {e}")

# ==========================================
# 5. 백그라운드 반복 실행 (5분 주기)
# ==========================================
if __name__ == "__main__":
    CHECK_INTERVAL_SECONDS = 300  # 300초 = 5분 간격 모니터링
    
    print("🚀 스포조이 실시간 선발투수 변경 감지기를 시작합니다.")
    print(f"⏱️ {CHECK_INTERVAL_SECONDS // 60}분 마다 체크하며 최초 발표 및 선발 변경 시 알림을 전송합니다.\n")
    
    while True:
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now_str}] 선발투수 등록 및 변경 여부 확인 중...")
        
        check_and_notify_pitchers()
        
        time.sleep(CHECK_INTERVAL_SECONDS)
