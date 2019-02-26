import dataclasses

from .keywords import KEYWORD_TO_INT
from .operators import all_operators, has_unbound_values

from .SExp import SExp


S_False = SExp(0)
S_True = SExp(1)



def create_rewrite_op(program, debug=False):
    from .compile import compile_to_sexp
    program_form = compile_to_sexp(program)

    def op_f(form, context):
        from .compile import dump, disassemble_sexp as ds
        inner_context = dataclasses.replace(context, env=form[1:])
        new_form = inner_context.reduce_f(program_form, inner_context)
        if debug:
            from .compile import disassemble_sexp as ds
            print("%s [%s]" % (ds(new_form), dump(form[1:])))
            print(ds(new_form))
        return context.reduce_f(new_form, context)

    return op_f


do_not = create_rewrite_op("(quasiquote (get (quote (1)) (unquote x0)))")
do_if = create_rewrite_op("(quasiquote (reduce (get (quote (unquote (list x1 x2))) (not (unquote x0)))))")
do_bool = create_rewrite_op("(quasiquote (not (not (unquote x0))))")
do_choose1 = create_rewrite_op("(cons #reduce (cons (list #get (cons #quote (cons (rest (env)))) x0)))")

QUASIQUOTE_KEYWORD = KEYWORD_TO_INT["quasiquote"]
UNQUOTE_KEYWORD = KEYWORD_TO_INT["unquote"]


def quasiquote(form, context, level):
    if form.is_list() and len(form) > 0:
        op = form[0].as_int()
        if op == QUASIQUOTE_KEYWORD:
            level += 1
        if op == UNQUOTE_KEYWORD:
            level -= 1
            if level == 0:
                if len(form) > 1:
                    return context.reduce_f(form[1], context)
        return SExp([quasiquote(_, context, level) for _ in form])

    return form


def do_quasiquote(form, context):
    if len(form) < 2:
        return S_False
    env = context.env
    if len(form) > 2:
        env = context.reduce_f(form[2], context)
        assert env.is_list()
    new_context = dataclasses.replace(context, env=env)
    return quasiquote(form[1], new_context, level=1)


def do_apply(form, context):
    return context.apply_f(form[1:], context)


def do_eval(form, context):
    env = SExp([])
    new_context = dataclasses.replace(context, env=env)
    return do_reduce(form, new_context)


def do_quote(form, context):
    if len(form) > 1:
        return form[1]
    return S_False


def do_case(form, context):
    for _ in form[1:]:
        if len(_) != 2:
            raise ValueError("not of form condition/action")
        condition, action = list(_)
        v = context.reduce_f(condition, context)
        if v.as_int():
            return context.reduce_f(action, context)
    return S_False


def do_env(form, context):
    r = context.env
    for _ in form[1:]:
        if r.is_list() and _.is_bytes() and _.as_int() < len(r):
            r = r[_.as_int()]
        else:
            return S_False
    return r


def do_reduce(form, context):
    if len(form) < 2:
        return S_False
    new_form = context.reduce_f(form[1], context)
    env = context.env
    if len(form) > 2:
        env = context.reduce_f(form[2], context)
    new_context = dataclasses.replace(context, env=env)
    return context.reduce_f(new_form, new_context)


def do_recursive_reduce(form, context):
    return SExp([form[0]] + [context.reduce_f(_, context) for _ in form[1:]])


def do_map(form, context):
    args = SExp([context.reduce_f(_, context) for _ in form[1:]])
    the_f = args[0]
    args = args[1]
    return SExp([context.apply_f(SExp([the_f, _]), context) for _ in args])


def build_reduce_lookup(remap, keyword_to_int):
    g = globals()
    d = all_operators(remap, keyword_to_int)
    for k, i in keyword_to_int.items():
        if k in remap:
            k = remap[k]
        f = g.get("do_%s" % k)
        if f:
            d[i] = f

    return d


def apply_f_for_lookup(reduce_lookup, reduce_default):
    def apply_f(form, context):
        if form[0].is_list():
            inner_context = dataclasses.replace(context, env=form[1:])
            new_form = inner_context.reduce_f(form[0], inner_context)
            return context.reduce_f(new_form, context)

        f = reduce_lookup.get(form[0].as_int())
        if f:
            return f(form, context)
        return reduce_default(form, context)

    return apply_f


def do_reduce_bytes(form, context):
    return form[1]


def do_reduce_var(form, context):
    form = form[1]
    index = form.var_index()
    env = context.env
    if 0 <= index < len(env):
        return env[index]
    return form


def make_and(form, context):
    form = SExp([DEFAULT_OPERATOR] + list(form))
    return context.apply_f(form, context)


def apply_macro(form, context):
    new_form = do_macro_expand(form, context)
    return context.reduce_f(new_form, context)


def do_macro_expand(form, context):
    env = do_recursive_reduce(form[1:], context)
    return macro_expand(env[0], env[1])


def macro_expand(form, env):
    if form.is_var():
        index = form.var_index()
        if 0 <= index < len(env):
            return env[index]
        raise ValueError("undefined variable x%d" % index)

    if form.is_bytes():
        return form

    assert form.is_list()
    if len(form) > 0 and form[0].as_int() == KEYWORD_TO_INT["menv"]:
        return env
    return SExp([macro_expand(_, env) for _ in form])


@dataclasses.dataclass
class ReduceContext:
    reduce_f: None
    env: SExp
    apply_f: None


def default_reduce_f(form: SExp, context: ReduceContext):
    if form.is_bytes():
        form = SExp([REDUCE_BYTES, form])

    if form.is_var():
        form = SExp([REDUCE_VAR, form])

    return context.apply_f(form, context)


REDUCE_LOOKUP = build_reduce_lookup(
    {"+": "add", "*": "multiply", "-": "subtract", "/": "divide"}, KEYWORD_TO_INT)
DEFAULT_OPERATOR = KEYWORD_TO_INT["and"]


REDUCE_VAR = SExp(KEYWORD_TO_INT["reduce_var"])
REDUCE_BYTES = SExp(KEYWORD_TO_INT["reduce_bytes"])


def reduce(form: SExp, env: SExp, reduce_f=None):
    reduce_f = reduce_f or default_reduce_f
    apply_f = apply_f_for_lookup(REDUCE_LOOKUP, do_recursive_reduce)
    context = ReduceContext(
        reduce_f=reduce_f, env=env, apply_f=apply_f)
    return reduce_f(form, context)
