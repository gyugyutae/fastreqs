"""환경설정(.env)을 읽는 모듈.

사용 예:
    config = Config.load()
    config.validate()
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DATA_DIR = 'data'
DEFAULT_MODEL = 'nvidia/nemotron-3-super-120b-a12b:free'
DEFAULT_END_KEYWORDS = '수고하셨습니다,회의 종료,오늘 회의는 여기까지'
FREE_MODEL_SUFFIX = ':free'


def _split_csv(raw_value):
    """쉼표로 나눈 값에서 빈 항목을 뺀 목록을 돌려준다."""
    return [item.strip() for item in raw_value.split(',') if item.strip()]


@dataclass
class Config:
    """실행에 필요한 설정 값.

    Attributes:
        data_dir: SQLite 상태와 잠금 파일을 두는 폴더.
        bot_token: Slack Bot 토큰(xoxb).
        app_token: Slack App 토큰(xapp).
        api_key: OpenRouter API 키.
        model: 사용할 무료 모델 이름.
        endings: 회의 종료로 보는 키워드.
        channels: 허용 채널 ID 집합.
    """

    data_dir: Path
    bot_token: str
    app_token: str
    api_key: str
    model: str
    endings: tuple[str, ...]
    channels: frozenset[str]

    @classmethod
    def load(cls):
        """.env와 환경 변수에서 설정을 읽어 돌려준다."""
        load_dotenv(ROOT / '.env', override=False)
        data_dir = Path(os.getenv('FASTREQS_DATA_DIR', DEFAULT_DATA_DIR))
        if not data_dir.is_absolute():
            data_dir = ROOT / data_dir
        endings = os.getenv('END_KEYWORDS', DEFAULT_END_KEYWORDS)
        return cls(
            data_dir=data_dir,
            bot_token=os.getenv('SLACK_BOT_TOKEN', ''),
            app_token=os.getenv('SLACK_APP_TOKEN', ''),
            api_key=os.getenv('OPENROUTER_API_KEY', ''),
            model=os.getenv('OPENROUTER_MODEL', DEFAULT_MODEL),
            endings=tuple(_split_csv(endings)),
            channels=frozenset(_split_csv(os.getenv('SLACK_CHANNEL_IDS', ''))),
        )

    def validate(self):
        """필수 설정이 모두 있는지 검사한다.

        Raises:
            ValueError: 무료 모델이 아니거나 필수 값이 비어 있는 경우.
        """
        if not self.model.endswith(FREE_MODEL_SUFFIX):
            raise ValueError('이번 MVP는 :free 모델만 사용합니다.')
        required = [
            ('SLACK_BOT_TOKEN', self.bot_token),
            ('SLACK_APP_TOKEN', self.app_token),
            ('OPENROUTER_API_KEY', self.api_key),
            ('OPENROUTER_MODEL', self.model),
        ]
        missing = [name for name, value in required if not value]
        if missing:
            raise ValueError('설정이 필요합니다: ' + ', '.join(missing))
