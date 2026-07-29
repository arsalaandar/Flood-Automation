import threading


class Submit:

    def __init__(self, page):

        self.page = page

        # Set whenever a dialog actually fires and gets handled. Used
        # by click_update() to actively wait for confirmation instead
        # of blindly sleeping a fixed duration - the confirmation
        # dialog's arrival time varies with server response time, and
        # native browser dialogs BLOCK all further page interaction
        # until dismissed.
        self.dialog_event = threading.Event()

        self.page.on("dialog", self._handle_dialog)

    def _handle_dialog(self, dialog):

        try:

            dialog.accept()

        except Exception:

            # Already accepted/dismissed by something else - fine,
            # nothing left to do.
            pass

        finally:

            self.dialog_event.set()

    def click_update(
        self,
        first_wait_ms=10000,
        retry_wait_ms=7000,
        max_retries=1
    ):
        """
        Clicks Update and waits for the confirmation dialog to fire -
        the wait returns as soon as the dialog actually appears, it
        doesn't sit for the full duration every time. If the dialog
        genuinely doesn't show up within first_wait_ms, clicks Update
        again (the first click may not have registered, or the
        postback was unusually slow) and waits a shorter retry_wait_ms
        for it. Only reports failure if the dialog never appears
        across all attempts.
        """

        try:

            self.dialog_event.clear()

            self.page.get_by_role(
                "button",
                name="Update"
            ).click()

            appeared = self.dialog_event.wait(
                timeout=first_wait_ms / 1000
            )

            attempt = 1

            while not appeared and attempt <= max_retries:

                print(
                    f"⚠ No confirmation dialog after {first_wait_ms}ms - "
                    f"retrying Update click (attempt {attempt + 1})"
                )

                self.dialog_event.clear()

                self.page.get_by_role(
                    "button",
                    name="Update"
                ).click()

                appeared = self.dialog_event.wait(
                    timeout=retry_wait_ms / 1000
                )

                attempt += 1

            if not appeared:

                print(
                    "⚠ No confirmation dialog appeared after "
                    f"{max_retries + 1} attempt(s) - the update may "
                    "not have gone through."
                )

                return False

            # Brief settle time after the dialog closes, before the
            # caller moves on to the next hour's navigation.
            self.page.wait_for_timeout(500)

            print("✓ Update Submitted")

            return True

        except Exception as e:

            print(f"Update Failed : {e}")

            return False