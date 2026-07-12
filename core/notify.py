"""데스크톱 알림 발송 공용 유틸 (모듈 C).

scheduler/run_scheduler.py 와 app/pages/3_관심종목_모니터링.py 양쪽에서
동일한 함수를 재사용한다 (수동 스캔 버튼을 눌러도, 자동 스케줄러가 돌아도
같은 방식으로 알림이 발송되도록 하기 위함).
"""

try:
    from plyer import notification
except Exception:  # plyer가 지원하지 않는 환경(headless 서버 등)에서도 죽지 않도록
    notification = None


def send_desktop_notification(title: str, message: str) -> None:
    """데스크톱 알림을 보낸다. plyer 미지원 환경이면 콘솔 출력으로 대체한다."""
    if notification is not None:
        try:
            notification.notify(title=title, message=message, timeout=10)
            return
        except Exception as e:
            print(f"[알림 발송 실패, 콘솔로 대체] {e}")
    print(f"[알림] {title}: {message}")
