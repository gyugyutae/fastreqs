import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

@dataclass
class Config:
    data_dir: Path
    bot_token: str
    app_token: str
    api_key: str
    model: str
    endings: tuple[str, ...]
    channels: frozenset[str]

    @classmethod
    def load(cls):
        load_dotenv(ROOT / '.env', override=False)
        location = Path(os.getenv('FASTREQS_DATA_DIR', 'data'))
        if not location.is_absolute(): location = ROOT / location
        return cls(location, os.getenv('SLACK_BOT_TOKEN', ''), os.getenv('SLACK_APP_TOKEN', ''),
                   os.getenv('OPENROUTER_API_KEY', ''), os.getenv('OPENROUTER_MODEL', 'nvidia/nemotron-3-super-120b-a12b:free'),
                   tuple(x.strip() for x in os.getenv('END_KEYWORDS', '수고하셨습니다,회의 종료,오늘 회의는 여기까지').split(',') if x.strip()),
                   frozenset(x.strip() for x in os.getenv('SLACK_CHANNEL_IDS', '').split(',') if x.strip()))

    def validate(self):
        if not self.model.endswith(":free"):
            raise ValueError("이번 MVP는 :free 모델만 사용합니다.")
        missing = [name for name, value in [('SLACK_BOT_TOKEN', self.bot_token), ('SLACK_APP_TOKEN', self.app_token),
                    ('OPENROUTER_API_KEY', self.api_key), ('OPENROUTER_MODEL', self.model)] if not value]
        if missing: raise ValueError('설정이 필요합니다: ' + ', '.join(missing))
