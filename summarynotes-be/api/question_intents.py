from typing import Dict, List

from fastapi import APIRouter

from db import fetch_question_intents
from schemas.interviews import QuestionIntentItem


router = APIRouter(prefix="/api/question-intents", tags=["question_intents"])


@router.get("", response_model=List[QuestionIntentItem])
def list_question_intents() -> List[Dict]:
    """
    获取所有 question intent。
    """
    return fetch_question_intents()
