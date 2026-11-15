from playwright.sync_api import expect


def open_detail_filter(page, field, *, match=True):
    page.locator('#open-filters').click()
    expect(page.locator('#filter-dialog')).to_be_visible()
    page.locator('#filter-extra > summary').click()
    page.locator('#filter-field').select_option(field)
    expect(page.locator('#filter-editor')).to_have_attribute('data-field', field)
    if match and page.locator('#filter-mode input[value="ALL"]').is_checked():
        page.locator('#filter-mode input[value="MATCH"]').check()
