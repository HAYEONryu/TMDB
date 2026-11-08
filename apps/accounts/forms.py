from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError


class LoginForm(forms.Form):
    phone = forms.CharField(label="아이디 또는 전화번호", max_length=32, widget=forms.TextInput(attrs={"autocomplete": "username", "placeholder": "아이디 또는 010-0000-0000", "autocapitalize": "none"}))
    password = forms.CharField(label="비밀번호", max_length=128, strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class PasswordChangeForm(forms.Form):
    current_password = forms.CharField(label="현재 비밀번호", max_length=128, strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    new_password = forms.CharField(label="새 비밀번호", min_length=8, max_length=128, strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    new_password_confirm = forms.CharField(label="새 비밀번호 확인", max_length=128, strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        value = self.cleaned_data["current_password"]
        if not self.user.check_password(value):
            raise ValidationError("현재 비밀번호가 일치하지 않습니다.")
        return value

    def clean(self):
        data = super().clean()
        new = data.get("new_password")
        if new:
            if new == "dodream" or self.user.check_password(new):
                self.add_error("new_password", "현재 비밀번호와 다른 비밀번호를 입력해 주세요.")
            try:
                password_validation.validate_password(new, self.user)
            except ValidationError as exc:
                self.add_error("new_password", exc)
        if new and data.get("new_password_confirm") and new != data["new_password_confirm"]:
            self.add_error("new_password_confirm", "새 비밀번호 확인이 일치하지 않습니다.")
        return data
