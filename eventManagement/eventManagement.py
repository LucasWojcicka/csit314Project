import reflex as rx
from rxconfig import config

class State(rx.State):
    """The app state."""

    ...


def index() -> rx.Component:
    # Welcome Page (Index)
    return rx.container(
        rx.color_mode.button(position="top-right"),
        rx.vstack(
            rx.heading("Event Management Application", size="9"),
            rx.text("Welcome",size="5"),
            rx.link(rx.button("login", size="4"), href="/form"),
            spacing="5",
            justify="center",
            min_height="85vh",
        ),
    )

class FormState(rx.State):
    form_data: dict = {}

    @rx.event
    def handleSubmit(self, formData: dict):
        """Handle the form submit."""
        self.form_data = formData


def form_example():
    return rx.container(
        rx.color_mode.button(position="top-right"),
        rx.container(
            rx.heading("Login Page", size="6", align="center")
        ),
        rx.container(
            rx.vstack(
                rx.form(
                    rx.vstack(
                        rx.input(
                            placeholder="First Name",
                            name="firstName",
                        ),
                        rx.input(
                            placeholder="Last Name",
                            name="lastName",
                        ),
                        rx.input(
                            placeholder="Email Address",
                            name="emailAddress",
                        ),
                        rx.hstack(
                            rx.checkbox("I agree to the Terms and Conditions", name="check"),
                        ),
                        rx.button("Submit", type="submit"),
                        align="center",
                    ),
                    on_submit=FormState.handleSubmit,
                    reset_on_submit=True,
                ),
            ),
        ),
    )    

app = rx.App()
app.add_page(index)
app.add_page(form_example, route="/form")