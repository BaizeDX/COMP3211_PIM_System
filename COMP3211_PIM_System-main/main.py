"""Composition root for the offline PIM command-line application (Design section 2)."""

from cli.controller import PIMController
from cli.parser import CommandParser
from cli.view import PIMView, _configure_stdio
from model.persistence import PIMFileStorage
from model.search import CriteriaRegistry, ExpressionParser
from model.service import PIMService


if __name__ == "__main__":
    _configure_stdio()
    expression_parser = ExpressionParser()
    criteria = CriteriaRegistry(expression_parser)
    service = PIMService(PIMFileStorage(), criteria, expression_parser)
    controller = PIMController(service, CommandParser(), PIMView())
    controller.run()
