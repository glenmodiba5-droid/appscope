from app.database import SessionLocal
from app.models.models import App, TrackedUser, Event, Session as SessionModel, Insight
from sqlalchemy import delete

def clean():
    db = SessionLocal()
    
    # Get your test app
    app = db.query(App).filter(App.owner_email == "test@appscope.com").first()
    if not app:
        print("Test app not found.")
        db.close()
        return

    print(f"Cleaning seed data for app: {app.name}")

    # Delete in order (foreign key dependencies)
    db.execute(delete(Insight).where(Insight.app_id == app.id))
    db.execute(delete(Event).where(Event.app_id == app.id))
    db.execute(delete(SessionModel).where(SessionModel.app_id == app.id))
    db.execute(delete(TrackedUser).where(TrackedUser.app_id == app.id))
    
    db.commit()
    print("Done. All seed data removed. Fresh start.")
    db.close()

if __name__ == "__main__":
    clean()