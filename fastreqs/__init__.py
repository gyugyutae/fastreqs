"""FastReqs: Slack 대화에서 요구사항 변경을 찾아 승인 후 문서에 반영하는 봇.

설계 클래스와 모듈 대응(docs/02-설계/design.md 기준, 이름은 설계 camelCase를
코드 snake_case로 그대로 옮긴다):
    SlackBot «View»                      -> slack_bot.SlackBot
    RequirementController «Controller»   -> controller.RequirementController
        ChatCollector                    -> chat_collector.ChatCollector
        AnalysisRunner                   -> analysis_runner.AnalysisRunner
        ApprovalProcessor                -> approval_processor.ApprovalProcessor
    RequirementAnalysisService «Model»   -> analysis_service
    LlmClient «Model»                    -> llm_client.OpenRouterClient
    RequirementDocumentRepository «Model» -> document_repository
    RequirementDocument «Model»          -> documents (Markdown 순수 함수)
    Candidate / Requirement / Conflict   -> records.CandidateRecord,
                                            models.Story, models.Conflict
"""
