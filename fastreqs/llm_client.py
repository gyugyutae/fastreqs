"""OpenRouter HTTP 호출만 맡는 LLM 클라이언트(설계의 LlmClient).

프롬프트 내용이나 결과 검증은 모른다. 일시 오류는 한 번만 다시 시도하고
Retry-After를 존중한다.

사용 예:
    client = OpenRouterClient(config)
    raw_json = client.complete(SYSTEM_PROMPT, content, schema)
"""

import time

import httpx

API_URL = 'https://openrouter.ai/api/v1/chat/completions'
REQUEST_TIMEOUT_SECONDS = 90
MAX_OUTPUT_TOKENS = 3000
MAX_ATTEMPTS = 2
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
DEFAULT_RETRY_DELAY_SECONDS = 2
MIN_RETRY_DELAY_SECONDS = 1
MAX_RETRY_DELAY_SECONDS = 60
HTTP_ERROR_THRESHOLD = 400
FORMAT_ERROR = '모델 결과 형식 검증 실패. 다시 분석해주세요.'
CONNECTION_ERROR = '모델 연결 실패. 입력은 유지됩니다.'


def _retry_delay(response):
    """응답의 Retry-After 헤더로 대기 시간(초)을 구한다."""
    raw_value = response.headers.get(
        'Retry-After', str(DEFAULT_RETRY_DELAY_SECONDS))
    try:
        return max(MIN_RETRY_DELAY_SECONDS, float(raw_value))
    except ValueError:
        return DEFAULT_RETRY_DELAY_SECONDS


class OpenRouterClient:
    """OpenRouter 채팅 API로 구조화 JSON을 요청한다.

    Attributes:
        config: model과 api_key를 가진 설정 객체.
    """

    def __init__(self, config):
        """설정을 보관한다."""
        self.config = config

    def _build_payload(self, system_prompt, user_content, schema):
        """요청 본문을 만든다."""
        return {
            'model': self.config.model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_content},
            ],
            'max_tokens': MAX_OUTPUT_TOKENS,
            'reasoning': {'effort': 'low'},
            'response_format': {
                'type': 'json_schema',
                'json_schema': {'name': 'requirements', 'strict': True,
                                'schema': schema},
            },
            'provider': {'require_parameters': True},
        }

    def _post(self, payload):
        """요청을 한 번 보내고 응답을 돌려준다."""
        headers = {'Authorization': 'Bearer ' + self.config.api_key}
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            return client.post(API_URL, headers=headers, json=payload)

    def complete(self, system_prompt, user_content, schema):
        """모델을 호출해 응답 메시지의 JSON 문자열을 돌려준다.

        Args:
            system_prompt: 시스템 지시문.
            user_content: 분석 자료(JSON 문자열).
            schema: 응답이 따라야 할 JSON 스키마.

        Returns:
            모델이 만든 JSON 문자열.

        Raises:
            RuntimeError: 연결 실패, HTTP 오류, 응답 형식 오류인 경우.
        """
        payload = self._build_payload(system_prompt, user_content, schema)
        for attempt in range(MAX_ATTEMPTS):
            is_last = attempt == MAX_ATTEMPTS - 1
            try:
                response = self._post(payload)
            except httpx.TransportError:
                if not is_last:
                    continue
                raise RuntimeError(CONNECTION_ERROR) from None
            if response.status_code in RETRYABLE_STATUS and not is_last:
                delay = _retry_delay(response)
                if delay > MAX_RETRY_DELAY_SECONDS:
                    raise RuntimeError(
                        f'호출 제한: {int(delay)}초 후 다시 분석해주세요.')
                time.sleep(delay)
                continue
            if response.status_code >= HTTP_ERROR_THRESHOLD:
                raise RuntimeError(
                    f'OpenRouter HTTP {response.status_code}: '
                    '키/무료 모델/호출 제한을 확인해주세요.')
            try:
                return response.json()['choices'][0]['message']['content']
            except (ValueError, KeyError, IndexError, TypeError):
                raise RuntimeError(FORMAT_ERROR) from None
        raise RuntimeError(CONNECTION_ERROR)
