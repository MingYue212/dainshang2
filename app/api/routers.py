import uuid

from fastapi import APIRouter

from app.api.domain.message import MsgType, ProcessResult, UserMsg
from app.api.schemas import ChatHistoryResponse, ChatRequest, ChatResponse

router = APIRouter()


@router.get("/api/chat", response_model=ChatResponse)
async def chat(
    chat_request: ChatRequest,
):
    # 1.将ChatRequest转换为UserMsg（交互模型-->领域模型）
    user_msg = _build_user_message(chat_request)


    # 2.调用DialogueService处理消息
    process_result = await dialogue_service.process_message(user_msg)

    # 3.将ProcessResult转换为ChatResponse（领域模型-->交互模型）
    chat_response = _build_chat_response(process_result)


def _build_chat_response(process_result: ProcessResult)->ChatResponse:
    """将ProcessResult转换为ChatResponse（领域模型-->交互模型）"""
    return ChatResponse(
        sender_id=process_result.sender_id,
        msg_id=process_result.msg_id,
        msgs=[
            BotMsgResponse(
                text=bot_msg.text,
                object=(
                    ChatObjectPayload(**bot_msg.object.to_dict())
                    if bot_msg.object
                    else None
                ),
            )
            for bot_msg in process_result.msgs

def _build_user_message(chat_request: ChatRequest)->UserMsg:
    """将ChatRequest转换为UserMsg（交互模型-->领域模型）"""
    dict_data = {
        "msg_id": chat_request.msg_id if chat_request.msg_id else str(uuid.uuid4()),
        "sender_id": chat_request.sender_id,
        # 补充type
        "type": MsgType.TEXT if chat_request.text else MsgType.OBJECT,
        "text": chat_request.text,
        "object": (
            {
                "type": chat_request.object.type,
                "id": chat_request.object.id,
                "title": chat_request.object.title,
                "attributes": chat_request.object.attributes,
            }
            if chat_request.object
            else None
        ),
    }
    return UserMsg.from_dict(dict_data)















@router.post("/api/chat/history", response_model=ChatHistoryResponse)
async def chat_history():
    pass
