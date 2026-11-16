"""Operate the shared app confirmation; before-unload dialogs stay browser-native."""
from playwright.sync_api import expect


def confirm_action(page, accept=True):
    dialog=page.locator('#action-confirm-dialog')
    expect(dialog).to_be_visible()
    dialog.locator('#action-confirm-accept' if accept else '#action-confirm-cancel').click()
