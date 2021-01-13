"""
Author       : zhangxianbing
Date         : 2020-12-27 09:22:14
LastEditors  : zhangxianbing
LastEditTime : 2021-01-13 15:25:25
Description  : JSONPath
"""
__version__ = "1.0.2"
__author__ = "zhangxianbing"

import json
import logging
import os
import re
from collections import defaultdict
from typing import Union

# pylint: disable=invalid-name,missing-function-docstring,missing-class-docstring,eval-used,logging-fstring-interpolation


def create_logger(name: str = None, level: Union[int, str] = logging.INFO):
    """Get or create a logger used for local debug."""

    formater = logging.Formatter(
        f"%(asctime)s-%(levelname)s-[{name}] %(message)s", datefmt="[%Y-%m-%d %H:%M:%S]"
    )

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(formater)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger


LOG = create_logger("jsonpath", os.getenv("PYLOGLEVEL", "INFO"))


class ExprSyntaxError(Exception):
    pass


class JSONPath:
    RESULT_TYPE = {
        "VALUE": "A list of specific values.",
        "PATH": "All path of specific values.",
    }

    SEP = ";"
    # regex patterns
    REP_PICKUP_QUOTE = re.compile(r"['](.*?)[']")
    REP_PICKUP_BRACKET = re.compile(r"[\[](.*?)[\]]")
    REP_PUTBACK_QUOTE = re.compile(r"#Q(\d+)")
    REP_PUTBACK_BRACKET = re.compile(r"#B(\d+)")
    REP_DOUBLEDOT = re.compile(r"\.\.")
    REP_DOT = re.compile(r"(?<!\.)\.(?!\.)")

    # operators
    REP_SLICE_CONTENT = re.compile(r"^(-?\d*)?:(-?\d*)?(:-?\d*)?$")
    REP_SELECT_CONTENT = re.compile(r"^([\w.']+)(, ?[\w.']+)+$")
    REP_FILTER_CONTENT = re.compile(
        r"@\.(.*?)(?=<=|>=|==|!=|>|<| in| not| is)|len\(@\.(.*?)\)"
    )

    # annotations
    segments: list
    lpath: int
    subx = defaultdict(list)
    result: list
    result_type: str

    def __init__(self, expr: str):
        expr = self._parse_expr(expr)
        self.segments = expr.split(JSONPath.SEP)
        self.lpath = len(self.segments)
        LOG.debug(f"segments  : {self.segments}")

    def parse(self, obj, result_type="VALUE"):
        if not isinstance(obj, (list, dict)):
            raise TypeError("obj must be a list or a dict.")

        if result_type not in JSONPath.RESULT_TYPE:
            raise ValueError(
                f"result_type must be one of {tuple(JSONPath.RESULT_TYPE.keys())}"
            )
        self.result_type = result_type

        self.result = []
        self._trace(obj, 0, "$")

        return self.result

    def _parse_expr(self, expr):
        LOG.debug(f"before expr : {expr}")

        expr = JSONPath.REP_PICKUP_QUOTE.sub(self._f_pickup_quote, expr)
        expr = JSONPath.REP_PICKUP_BRACKET.sub(self._f_pickup_bracket, expr)
        expr = JSONPath.REP_DOUBLEDOT.sub(f"{JSONPath.SEP}..{JSONPath.SEP}", expr)
        expr = JSONPath.REP_DOT.sub(JSONPath.SEP, expr)
        expr = JSONPath.REP_PUTBACK_BRACKET.sub(self._f_putback_bracket, expr)
        expr = JSONPath.REP_PUTBACK_QUOTE.sub(self._f_putback_quote, expr)
        if expr.startswith("$;"):
            expr = expr[2:]

        LOG.debug(f"after expr  : {expr}")
        return expr

    def _f_pickup_quote(self, m):
        n = len(self.subx["#Q"])
        self.subx["#Q"].append(m.group(1))
        return f"#Q{n}"

    def _f_pickup_bracket(self, m):
        n = len(self.subx["#B"])
        self.subx["#B"].append(m.group(1))
        return f".#B{n}"

    def _f_putback_quote(self, m):
        return self.subx["#Q"][int(m.group(1))]

    def _f_putback_bracket(self, m):
        return self.subx["#B"][int(m.group(1))]

    @staticmethod
    def _f_brackets(m):
        ret = "__obj"
        for e in m.group(1).split("."):
            ret += '["%s"]' % e
        return ret

    @staticmethod
    def _traverse(f, obj, i: int, path: str, *args):
        if isinstance(obj, list):
            for idx, v in enumerate(obj):
                f(v, i, f"{path}{JSONPath.SEP}{idx}", *args)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                f(v, i, f"{path}{JSONPath.SEP}{k}", *args)

    @staticmethod
    def _getattr(obj: dict, path: str):
        r = obj
        for k in path.split("."):
            try:
                r = r.get(k)
            except (AttributeError, KeyError) as err:
                LOG.error(err)
                return None

        return r

    @staticmethod
    def _sorter(obj, sortbys):
        for sortby in sortbys.split(",")[::-1]:
            if sortby.startswith("~"):
                obj.sort(
                    key=lambda t, k=sortby: JSONPath._getattr(t[1], k[1:]), reverse=True
                )
            else:
                obj.sort(key=lambda t, k=sortby: JSONPath._getattr(t[1], k))

    def _filter(self, obj, i: int, path: str, step: str):
        r = False
        try:
            r = eval(step, None, {"__obj": obj})
        except Exception as err:
            LOG.error(err)
        if r:
            self._trace(obj, i, path)

    def _trace(self, obj, i: int, path):
        """Perform operation on object.

        Args:
            obj ([type]): current operating object
            i (int): current operation specified by index in self.segments
        """

        # store
        if i >= self.lpath:
            if self.result_type == "VALUE":
                self.result.append(obj)
            elif self.result_type == "PATH":
                self.result.append(path)
            LOG.debug(f"path: {path} | value: {obj}")
            return

        step = self.segments[i]

        # wildcard
        if step == "*":
            self._traverse(self._trace, obj, i + 1, path)
            return

        # recursive descent
        if step == "..":
            self._trace(obj, i + 1, path)
            self._traverse(self._trace, obj, i, path)
            return

        # get value from list
        if isinstance(obj, list) and step.isdigit():
            ikey = int(step)
            if ikey < len(obj):
                self._trace(obj[ikey], i + 1, f"{path}{JSONPath.SEP}{step}")
            return

        # get value from dict
        if isinstance(obj, dict) and step in obj:
            self._trace(obj[step], i + 1, f"{path}{JSONPath.SEP}{step}")
            return

        # slice
        if isinstance(obj, list) and JSONPath.REP_SLICE_CONTENT.fullmatch(step):
            obj = list(enumerate(obj))
            vals = eval(f"obj[{step}]")
            for idx, v in vals:
                self._trace(v, i + 1, f"{path}{JSONPath.SEP}{idx}")
            return

        # select
        if isinstance(obj, dict) and JSONPath.REP_SELECT_CONTENT.fullmatch(step):
            for k in step.split(","):
                if k in obj:
                    self._trace(obj[k], i + 1, f"{path}{JSONPath.SEP}{k}")
            return

        # filter
        if step.startswith("?(") and step.endswith(")"):
            step = step[2:-1]
            step = JSONPath.REP_FILTER_CONTENT.sub(self._f_brackets, step)
            self._traverse(self._filter, obj, i + 1, path, step)
            return

        # sorter
        if step.startswith("/(") and step.endswith(")"):
            if isinstance(obj, list):
                obj = list(enumerate(obj))
                self._sorter(obj, step[2:-1])
                for idx, v in obj:
                    self._trace(v, i + 1, f"{path}{JSONPath.SEP}{idx}")
            elif isinstance(obj, dict):
                obj = list(obj.items())
                self._sorter(obj, step[2:-1])
                for k, v in obj:
                    self._trace(v, i + 1, f"{path}{JSONPath.SEP}{k}")
            else:
                raise ExprSyntaxError("sorter must acting on list or dict")
            return

        # field-extractor
        if step.startswith("(") and step.endswith(")"):
            if isinstance(obj, dict):
                obj_ = {}
                for k in step[1:-1].split(","):
                    obj_[k] = obj.get(k)
                self._trace(obj_, i + 1, path)
            else:
                raise ExprSyntaxError("field-extractor must acting on list or dict")

            return


if __name__ == "__main__":
    with open("test/data/2.json", "rb") as f:
        d = json.load(f)
    D = JSONPath("$[bicycle, scores]").parse(d, "VALUE")
    print(D)
    for v in D:
        print(v)
