from django.test import Client
from apps.accounts.models import User

TEST_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STRONG_PASSWORD = "Forest!River2026"


def user(phone="01000000001", name="가상사용자", role=User.Role.EMPLOYEE, initial=True):
    return User.objects.create_user(phone, name, "dodream" if initial else STRONG_PASSWORD,
                                    role=role, must_change_password=initial)


def login(account, client=None, password=None):
    client = client or Client()
    response = client.post("/auth/login", {"phone": account.phone_normalized,
                                           "password": password or ("dodream" if account.must_change_password else STRONG_PASSWORD)}, content_type="application/json")
    assert response.status_code == 200, response.content
    return client


def password_data(current="dodream", new=STRONG_PASSWORD):
    return {"current_password": current, "new_password": new, "new_password_confirm": new}
