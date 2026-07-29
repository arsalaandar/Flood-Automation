from playwright.sync_api import TimeoutError


class Waits:

    @staticmethod
    def wait_until_value(locator, expected, timeout=5000):

        try:

            locator.page.wait_for_function(
                """
                ([element, expected]) => element.value.trim() === String(expected)
                """,
                arg=[locator.element_handle(), expected],
                timeout=timeout
            )

            return True

        except TimeoutError:

            return False