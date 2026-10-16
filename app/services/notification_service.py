import os
import json
import logging
from datetime import date, datetime, timezone
from typing import Optional, Tuple
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student import Student
from app.models.profile import Profile
from app.models.device_token import DeviceToken
from app.models.notification_log import NotificationLog

logger = logging.getLogger("notification_service")

# Global flag to track Firebase initialization
_firebase_initialized = False

def init_firebase() -> bool:
    """Initialize Firebase Admin SDK if credentials are available."""
    global _firebase_initialized
    if _firebase_initialized:
        return True

    try:
        import firebase_admin
        from firebase_admin import credentials

        if firebase_admin._apps:
            _firebase_initialized = True
            return True

        cred_path = os.getenv("FIREBASE_CREDENTIALS") or os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        if cred_path:
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                _firebase_initialized = True
                logger.info("Firebase Admin initialized via credentials file.")
                return True
            else:
                try:
                    cred_dict = json.loads(cred_path)
                    cred = credentials.Certificate(cred_dict)
                    firebase_admin.initialize_app(cred)
                    _firebase_initialized = True
                    logger.info("Firebase Admin initialized via JSON credentials string.")
                    return True
                except Exception:
                    logger.warning("FIREBASE_CREDENTIALS / FIREBASE_SERVICE_ACCOUNT_JSON neither valid file path nor JSON string.")
        
        project_id = os.getenv("FIREBASE_PROJECT_ID")
        if project_id:
            firebase_admin.initialize_app(options={"projectId": project_id})
            _firebase_initialized = True
            logger.info("Firebase Admin initialized with projectId: %s", project_id)
            return True

        logger.info("Firebase credentials not configured; running in mock notification mode.")
        return False
    except Exception as e:
        logger.warning(f"Could not initialize Firebase Admin: {e}; running in mock notification mode.")
        return False


async def notify_parent_on_absent(
    db: AsyncSession,
    student_id: str,
    attendance_date: date,
    action_type: str,
    marked_by_user_id: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Sends push notification to the parent when a child is marked absent.
    Rules:
    - Send ONLY ONCE per student per day (on first transition to absent).
    - Failures must never break the attendance save.
    - Prunes invalid/unregistered tokens.
    """
    try:
        # 1. Fetch student and parent
        student_res = await db.execute(select(Student).where(Student.id == student_id))
        student = student_res.scalars().first()
        if not student:
            return False, "Student not found"
        if not student.parent_id:
            return False, "Student has no assigned parent"

        parent_id = str(student.parent_id)

        # 2. Check duplicate suppression: send ONLY ONCE per student per day
        logs_res = await db.execute(
            select(NotificationLog).where(
                NotificationLog.user_id == parent_id,
                NotificationLog.status == "sent"
            )
        )
        existing_logs = logs_res.scalars().all()
        date_str = attendance_date.isoformat()
        
        for log in existing_logs:
            if log.data_payload and isinstance(log.data_payload, dict):
                if (
                    log.data_payload.get("type") == "attendance_absent"
                    and log.data_payload.get("student_id") == str(student.id)
                    and log.data_payload.get("attendance_date") == date_str
                ):
                    logger.info(
                        f"Suppressed duplicate absent notification for student {student.id} on date {date_str}"
                    )
                    return True, "Notification suppressed: already sent for this student today."

        title = f"Absence Alert: {student.first_name} {student.last_name}"
        body = f"{student.first_name} has been marked absent for {action_type} on {date_str}."
        data_payload = {
            "type": "attendance_absent",
            "student_id": str(student.id),
            "attendance_date": date_str,
            "action_type": action_type,
            "marked_by": str(marked_by_user_id) if marked_by_user_id else None
        }

        # 3. Fetch active device tokens for the parent
        tokens_res = await db.execute(select(DeviceToken).where(DeviceToken.user_id == parent_id))
        tokens = list(tokens_res.scalars().all())

        if not tokens:
            # Record suppressed log due to no tokens
            suppressed_log = NotificationLog(
                user_id=parent_id,
                title=title,
                body=body,
                data_payload=data_payload,
                status="suppressed",
                error_message="No registered device tokens for parent",
                sent_at=datetime.now(timezone.utc)
            )
            db.add(suppressed_log)
            await db.commit()
            return True, "No device tokens registered for parent; logged as suppressed."

        # 4. Attempt sending
        is_fb = init_firebase()
        sent_count = 0
        failed_count = 0
        error_msg = None

        if is_fb:
            try:
                from firebase_admin import messaging

                tokens_to_prune = []
                for dt in tokens:
                    try:
                        message = messaging.Message(
                            notification=messaging.Notification(
                                title=title,
                                body=body
                            ),
                            data={k: str(v) for k, v in data_payload.items() if v is not None},
                            token=dt.token
                        )
                        messaging.send(message)
                        sent_count += 1
                    except messaging.UnregisteredError:
                        logger.info(f"FCM token unregistered; pruning {dt.token[:12]}...")
                        tokens_to_prune.append(dt)
                        failed_count += 1
                    except messaging.SenderIdMismatchError:
                        logger.info(f"FCM token sender mismatch; pruning {dt.token[:12]}...")
                        tokens_to_prune.append(dt)
                        failed_count += 1
                    except Exception as token_err:
                        err_str = str(token_err).lower()
                        if "not registered" in err_str or "invalid" in err_str:
                            tokens_to_prune.append(dt)
                        logger.warning(f"Failed sending FCM message to token: {token_err}")
                        failed_count += 1
                        error_msg = str(token_err)

                # Prune invalid tokens
                for bad_token in tokens_to_prune:
                    await db.delete(bad_token)
                
            except Exception as fcm_err:
                logger.error(f"FCM messaging failed: {fcm_err}")
                error_msg = str(fcm_err)
        else:
            # Mock mode: consider successful
            sent_count = len(tokens)

        # 5. Record notification log
        final_status = "sent" if sent_count > 0 else "failed"
        log_entry = NotificationLog(
            user_id=parent_id,
            title=title,
            body=body,
            data_payload=data_payload,
            status=final_status,
            error_message=error_msg,
            sent_at=datetime.now(timezone.utc)
        )
        db.add(log_entry)
        await db.commit()
        return True, f"Notification processed: {final_status}"

    except Exception as e:
        logger.error(f"Error in notify_parent_on_absent: {e}", exc_info=True)
        # Failures must NEVER break the attendance save
        return False, str(e)


async def notify_parent_on_route_change_review(
    db: AsyncSession,
    parent_id: str,
    student_name: str,
    status_decision: str,
    notes: Optional[str] = None
) -> Tuple[bool, str]:
    """Sends notification to parent when their route change request is approved or rejected."""
    try:
        title = f"Route Change Request: {status_decision.capitalize()}"
        body = f"Your route change request for {student_name} has been {status_decision}."
        if notes:
            body += f" Note: {notes}"

        data_payload = {
            "type": "route_change_decision",
            "decision": status_decision,
            "student_name": student_name
        }

        # Check tokens
        tokens_res = await db.execute(select(DeviceToken).where(DeviceToken.user_id == parent_id))
        tokens = list(tokens_res.scalars().all())

        is_fb = init_firebase()
        if is_fb and tokens:
            try:
                from firebase_admin import messaging
                for dt in tokens:
                    try:
                        message = messaging.Message(
                            notification=messaging.Notification(title=title, body=body),
                            data={k: str(v) for k, v in data_payload.items() if v is not None},
                            token=dt.token
                        )
                        messaging.send(message)
                    except Exception:
                        pass
            except Exception:
                pass

        log_entry = NotificationLog(
            user_id=parent_id,
            title=title,
            body=body,
            data_payload=data_payload,
            status="sent",
            sent_at=datetime.now(timezone.utc)
        )
        db.add(log_entry)
        await db.commit()
        return True, "Notification sent"
    except Exception as e:
        logger.error(f"Error in notify_parent_on_route_change_review: {e}")
        return False, str(e)
