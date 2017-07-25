import time
import random

from functools import wraps
from threading import Thread
from sqlalchemy import func

from conf import BREW_COUNTDOWN
from models import Server, Customer, get_session, User
from slack_client import sc
from utils import post_message


def delay(seconds):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            time.sleep(seconds)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def brew_countdown(channel):
    Thread(target=_brew_countdown, args=(channel,)).start()


@delay(BREW_COUNTDOWN)
def _brew_countdown(channel):
    session = get_session()

    server = session.query(Server).filter_by(completed=False).first()
    if not server:
        return

    server.completed = True
    customers = session.query(Customer).filter_by(server_id=server.id)

    for customer in customers.all():
        customer.user.teas_drunk += 1
        customer.user.teas_received += 1
        server.user.teas_brewed += 1

    server.user.teas_brewed += 1  # Account for server's tea
    server.user.teas_drunk += 1
    server.user.times_brewed += 1

    if not customers.count():
        session.commit()
        return post_message('Time is up! Looks like no one else wants a cuppa.', channel)

    # There must be at least 1 customer to get a nomination point.
    server.user.nomination_points += 1
    session.commit()

    colors = ["#1d2d3b", "#52aad8", "#273a4b"]

    attachments = []
    index = 0
    for customer in customers:
        attachments.append({
            "author_icon": customer.user.picture,
            "author_name": "@%s" % customer.user.username,
            "color": colors[index % len(colors)],
            "text": "%s would like %s" % (customer.user.display_name, customer.user.tea_type),
            "footer": "%d brewed | %d received | %s consumed" % (customer.user.teas_brewed, customer.user.teas_received, customer.user.teas_drunk),
        })
        index = index + 1

    return post_message(
        'Time is up!',
        channel,
        attachments=attachments
    )


def update_slack_users():
    """
    Periodic task to update slack user info
    """
    session = get_session()
    try:
        session.execute("ALTER TABLE user ADD COLUMN picture VARCHAR(255);")
    except Exception:
        pass
    slack_users = sc.api_call('users.list')
    if not slack_users['ok']:
        return

    for member in slack_users['members']:
        slack_id = member.get('id')
        username = member.get('name')
        email = member.get('profile').get('email', '')
        real_name = member.get('profile').get('real_name', '')
        first_name = member.get('profile').get('first_name', '')
        last_name = member.get('profile').get('last_name', '')
        picture = member.get('profile').get('image_48', '')
        deleted = member.get('profile').get('deleted')

        user = session.query(User).filter_by(slack_id=slack_id).first()
        if user:
            user.username = username
            user.email = email
            user.real_name = real_name
            user.first_name = first_name
            user.last_name = last_name
            user.deleted = deleted
            user.picture = picture
        else:
            session.add(User(
                slack_id=slack_id,
                username=username,
                email=email,
                real_name=real_name,
                first_name=first_name,
                last_name=last_name,
                picture=picture,
                deleted=deleted
            ))

        session.commit()
