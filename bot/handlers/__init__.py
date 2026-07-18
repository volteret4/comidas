from telegram.ext import Application

from . import dishes, planning, shopping


def register_handlers(application: Application) -> None:
    dishes.register(application)
    planning.register(application)
    shopping.register(application)
