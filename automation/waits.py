from playwright.sync_api import TimeoutError


class Waits:

    @staticmethod
    def wait_until_value(locator, expected, timeout=5000):

        try:

            locator.page.wait_for_function(
                """
                ([element, expected]) => {
                    const val = element.value.trim();
                    // Try comparing as numbers first (e.g. 19.0 == 19)
                    const numVal = parseFloat(val);
                    const numExp = parseFloat(expected);
                    if (!isNaN(numVal) && !isNaN(numExp)) {
                        return numVal === numExp;
                    }
                    return val === String(expected);
                }
                """,
                arg=[locator.element_handle(), expected],
                timeout=timeout
            )

            return True

        except TimeoutError:

            return False