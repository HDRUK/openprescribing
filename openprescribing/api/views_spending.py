from django.shortcuts import get_object_or_404

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.exceptions import APIException, NotFound

from common.utils import nhs_titlecase, parse_date
from frontend.models import Practice, PCT, STP, RegionalTeam, PCN, NCSOConcession
from frontend.price_per_unit.prescribing_breakdown import (
    get_prescribing,
    get_ppu_breakdown,
    get_mean_ppu,
)
from frontend.price_per_unit.savings import (
    get_savings_for_orgs,
    get_all_savings_for_orgs,
)
from frontend.ghost_branded_generics import (
    get_ghost_branded_generic_spending,
    get_total_ghost_branded_generic_spending,
)
from matrixstore.db import get_db, get_row_grouper

from . import view_utils as utils


class NotValid(APIException):
    status_code = 400
    default_detail = "The code you provided is not valid"


class BadDate(NotFound):
    def __init__(self, date):
        try:
            parsed = parse_date(date)
            # Ensures that strings like "2020-1-1" are treated as format errors
            # even though they can be parsed correctly
            if parsed.isoformat() != date:
                raise ValueError()
        except ValueError:
            detail = "Dates must be in YYYY-MM-DD format"
        else:
            detail = "Date is outside the 5 years of data available"
        super().__init__(detail)


def _get_org_or_404(org_code, org_type=None):
    if not org_type and org_code:
        org_type = "ccg" if len(org_code) == 3 else "practice"
    if org_type.lower() == "ccg":
        org = get_object_or_404(PCT, pk=org_code)
    elif org_type == "practice":
        org = get_object_or_404(Practice, pk=org_code)
    else:
        raise ValueError(org_type)
    return org


@api_view(["GET"])
def bubble(request, format=None):
    """
    Returns data relating to price-per-unit, in a format suitable for
    use in Highcharts bubble chart.
    """
    code = request.query_params.get("bnf_code", "")
    date = request.query_params.get("date")
    highlight = request.query_params.get("highlight", None)
    focus = request.query_params.get("focus", None) and highlight
    if not date:
        raise NotValid("You must supply a date")

    if highlight:
        highlight_org_id = highlight
        highlight_org_type = (
            "standard_ccg" if len(highlight_org_id) == 3 else "practice"
        )
    else:
        highlight_org_type = "all_standard_practices"
        highlight_org_id = None

    if focus:
        org_type = highlight_org_type
        org_id = highlight_org_id
    else:
        org_type = "all_standard_practices"
        org_id = None

    prescribing = get_prescribing(code, date)
    ppu_breakdown = get_ppu_breakdown(prescribing, org_type, org_id)
    mean_ppu = get_mean_ppu(prescribing, highlight_org_type, highlight_org_id)

    categories = []
    series = []

    for n, presentation in enumerate(ppu_breakdown):
        categories.append(
            {"name": presentation["name"], "is_generic": presentation["is_generic"]}
        )
        for ppu_value, quantity_at_ppu in presentation["quantity_at_each_ppu"]:
            series.append(
                {
                    "x": n + 1,
                    "y": ppu_value / 100,
                    "z": quantity_at_ppu,
                    "name": presentation["name"],
                    "mean_ppu": presentation["mean_ppu"] / 100,
                }
            )
    return Response(
        {
            "plotline": mean_ppu / 100 if mean_ppu is not None else None,
            "series": series,
            "categories": categories,
        }
    )


@api_view(["GET"])
def price_per_unit(request, format=None):
    """
    Returns price per unit data for presentations and practices or
    CCGs
    """
    entity_code = request.query_params.get("entity_code", "")
    entity_type = request.query_params.get("entity_type", "").lower()
    child_org_type = request.query_params.get("child_org_type", "")
    date = request.query_params.get("date")
    bnf_code = request.query_params.get("bnf_code")
    aggregate = bool(request.query_params.get("aggregate"))
    if not date:
        raise NotValid("You must supply a date")
    if not (entity_code or bnf_code or aggregate):
        raise NotValid(
            "You must supply a value for entity_code or bnf_code, or set the "
            "aggregate flag"
        )
    if not entity_type:
        entity_type = "ccg" if len(entity_code) == 3 else "practice"

    filename = date
    if bnf_code:
        filename += "-%s" % bnf_code
    if entity_code:
        filename += "-%s" % entity_code

    # This not a particularly orthogonal API. Below we're just replicating the
    # logic of the original API which we can think about simplifying later.
    #
    # Handle the special All England case
    if aggregate:
        # If we're not looking at a specific code then we want to aggregate all
        # practices together
        if not bnf_code:
            entity_type = "all_standard_practices"
            entity_codes = [None]
        # Otherwise we want the results over all CCGs
        else:
            entity_type = "ccg"
            entity_codes = get_row_grouper(entity_type).ids
    else:
        # If we don't specify a particular org then we want all orgs of that
        # type
        if not entity_code:
            entity_codes = get_row_grouper(entity_type).ids
        else:
            # When looking at a specific BNF code for a specific CCG we
            # actually want the results over its practices. And the same goes
            # if we've explicitly asked for practice level data
            if entity_type == "ccg" and (bnf_code or child_org_type == "practice"):
                entity_type = "practice"
                entity_codes = _get_practice_codes_for_ccg(entity_code)
            # Otherwise we should just show the specified org
            else:
                entity_codes = [entity_code]

    if bnf_code:
        results = get_savings_for_orgs(bnf_code, date, entity_type, entity_codes)
    else:
        results = get_all_savings_for_orgs(date, entity_type, entity_codes)

    # Fetch the names of all the orgs involved and prepare to reformat the
    # response to match the old API
    if entity_type == "practice":
        org_id_field = "practice"
        org_name_field = "practice_name"
        org_names = {
            code: nhs_titlecase(name)
            for (code, name) in Practice.objects.filter(
                code__in=entity_codes
            ).values_list("code", "name")
        }
    elif entity_type == "ccg":
        org_id_field = "pct"
        org_name_field = "pct_name"
        org_names = {
            code: nhs_titlecase(name)
            for (code, name) in PCT.objects.filter(code__in=entity_codes).values_list(
                "code", "name"
            )
        }
    elif entity_type == "all_standard_practices":
        org_id_field = "pct"
        org_name_field = "pct_name"
        org_names = {None: "NHS England"}
    else:
        raise ValueError(entity_type)

    # All BNF codes which had a price concession that month
    concession_codes = set(_get_concession_bnf_codes(date))

    # Reformat response to match the old API
    for row in results:
        org_id = row.pop("org_id")
        row[org_id_field] = org_id
        row[org_name_field] = org_names[org_id]
        row["price_concession"] = row["presentation"] in concession_codes

    response = Response(results)
    if request.accepted_renderer.format == "csv":
        filename = "%s-ppd.csv" % (filename)
        response["content-disposition"] = "attachment; filename=%s" % filename
    return response


def _get_practice_codes_for_ccg(ccg_id):
    practices = Practice.objects.filter(ccg_id=ccg_id, setting=4)
    # Remove any practice codes with no associated prescribing
    prescribing_practice_codes = get_row_grouper("practice").offsets.keys()
    return [
        code
        for code in practices.values_list("code", flat=True)
        if code in prescribing_practice_codes
    ]


def _get_concession_bnf_codes(date):
    """
    Return list of BNF codes to which NCSO price concessions were applied in
    the given month.
    """
    return (
        NCSOConcession.objects.filter(date=date, vmpp__isnull=False)
        .values_list("vmpp__bnf_code", flat=True)
        .distinct()
    )


@api_view(["GET"])
def ghost_generics(request, format=None):
    """
    Returns price per unit data for presentations and practices or CCGs
    """
    # We compare the price that should have been paid for a generic, with the
    # price actually paid. The price that should have been paid comes from the
    # Drug Tariff; however, we can't use that data reliably because the BSA use
    # an internal copy that doesn't match with the published version (see #1318
    # for an explanation). Therefore, we use the median price paid nationally
    # as a proxy for the Drug Tariff price.
    #
    # We exclude trivial amounts of saving on the grounds these should
    # be actionable savings.
    date = request.query_params.get("date")
    entity_code = request.query_params.get("entity_code")
    entity_type = request.query_params.get("entity_type").lower()
    group_by = request.query_params.get("group_by", "practice")
    if not date:
        raise NotValid("You must supply a date")

    if group_by == "presentation":
        results = get_ghost_branded_generic_spending(date, entity_type, [entity_code])
    elif group_by == "all":
        total = get_total_ghost_branded_generic_spending(date, entity_type, entity_code)
        results = [{"possible_savings": total}]
    elif group_by == "practice":
        if entity_type == "practice":
            child_org_type = "practice"
            child_org_ids = [entity_code]
        elif entity_type == "ccg":
            child_org_type = "practice"
            child_org_ids = _get_practice_codes_for_ccg(entity_code)
        else:
            raise ValueError("Unhanlded org_type: {}".format(entity_type))
        results = get_ghost_branded_generic_spending(
            date, child_org_type, child_org_ids
        )
    else:
        raise ValueError(group_by)

    # Add a practice/CCG columns for consistency with original API
    for result in results:
        result[entity_type] = entity_code

    response = Response(results)
    if request.accepted_renderer.format == "csv":
        filename = "ghost-generics-%s-%s" % (entity_code, date)
        filename = "%s.csv" % (filename)
        response["content-disposition"] = "attachment; filename=%s" % filename
    return response


@api_view(["GET"])
def total_spending(request, format=None):
    codes = utils.param_to_list(request.query_params.get("code", []))
    codes = utils.get_bnf_codes_from_number_str(codes)
    data = _get_total_prescribing_entries(codes)
    response = Response(list(data))
    if request.accepted_renderer.format == "csv":
        filename = "spending-{}.csv".format("-".join(codes))
        response["content-disposition"] = "attachment; filename={}".format(filename)
    return response


def _get_total_prescribing_entries(bnf_code_prefixes):
    """
    Yields a dict for each date in our data giving the total prescribing values
    across all practices for all presentations matching the supplied BNF code
    prefixes
    """
    db = get_db()
    items_matrix, quantity_matrix, actual_cost_matrix = _get_prescribing_for_codes(
        db, bnf_code_prefixes
    )
    # If no data at all was found, return early which results in an empty
    # iterator
    if items_matrix is None:
        return
    # This will sum over every practice (whether setting 4 or not) which might
    # not seem like what we want but is what the original API did (it was
    # powered by the `vw__presentation_summary` table which summed over all
    # practice types)
    group_all = get_row_grouper("all_practices")
    items_matrix = group_all.sum(items_matrix)
    quantity_matrix = group_all.sum(quantity_matrix)
    actual_cost_matrix = group_all.sum(actual_cost_matrix)
    # Yield entries for each date (unlike _get_prescribing_entries below we
    # return a value for each date even if it's zero as this is what the
    # original API did)
    for date, col_offset in sorted(db.date_offsets.items()):
        # The grouped matrices only ever have one row (which represents the
        # total over all practices) so we always want row 0 in our index
        index = (0, col_offset)
        yield {
            "items": items_matrix[index],
            "quantity": quantity_matrix[index],
            "actual_cost": round(actual_cost_matrix[index], 2),
            "date": date,
        }


@api_view(["GET"])
def tariff(request, format=None):
    # This view uses raw SQL as we cannot produce the LEFT OUTER JOIN using the
    # ORM.
    codes = utils.param_to_list(request.query_params.get("codes", []))

    # On 2019-05-14 someone set up a job on Zapier which requests the entire
    # (35MB) drug tariff every 10 minutes. We'd like Cloudflare to cache this
    # for us but we don't want to cache every reponse from this endpoint as it
    # contains NCSO concession data which gets updated regularly. As our
    # internal uses of this endpoint never involve requesting the entire
    # tariff, a pragmatic -- if hacky -- compromise is to just cache in the
    # case that the request doesn't specify any BNF codes.
    response_should_be_cached = not codes

    query = """
    SELECT tariffprice.date AS date,
           tariffprice.price_pence AS price_pence,
           vmpp.nm AS vmpp,
           vmpp.vppid AS vmpp_id,
           vmpp.bnf_code AS product,
           ncso_concession.price_pence AS concession,
           dtpaymentcategory.descr AS tariff_category,
           vmpp.qtyval AS pack_size
    FROM frontend_tariffprice tariffprice
        INNER JOIN dmd_dtpaymentcategory dtpaymentcategory
            ON tariffprice.tariff_category_id = dtpaymentcategory.cd
        INNER JOIN dmd_vmpp vmpp
            ON tariffprice.vmpp_id = vmpp.vppid
        LEFT OUTER JOIN frontend_ncsoconcession ncso_concession
            ON (tariffprice.date = ncso_concession.date
                AND tariffprice.vmpp_id = ncso_concession.vmpp_id)
    """

    if codes:
        query += " WHERE vmpp.bnf_code IN ("
        query += ",".join("%s" for _ in range(len(codes)))
        query += ")"
        params = [codes]
    else:
        params = None

    query += " ORDER BY date"

    data = utils.execute_query(query, params)
    response = Response(data)
    if request.accepted_renderer.format == "csv":
        filename = "tariff.csv"
        response["content-disposition"] = "attachment; filename=%s" % filename
    if response_should_be_cached:
        response["cache-control"] = "max-age={}, public".format(60 * 60 * 8)
    return response


@api_view(["GET"])
def spending_by_org(request, format=None, org_type=None):
    codes = utils.param_to_list(request.query_params.get("code", []))
    codes = utils.get_bnf_codes_from_number_str(codes)
    org_ids = utils.param_to_list(request.query_params.get("org", []))
    org_type = request.query_params.get("org_type", org_type)
    date = request.query_params.get("date", None)

    # Accept both cases of CCG (better to fix this specific string rather than
    # make the whole API case-insensitive)
    if org_type == "CCG":
        org_type = "ccg"

    # Some special case handling for practices
    if org_type == "practice":
        # Translate any CCG codes into the codes of all practices in that CCG
        org_ids = utils.get_practice_ids_from_org(org_ids)
        # Due to the number of practices we only return data for all practices
        # if a single date is specified
        if not date and not org_ids:
            return Response(
                "Error: You must supply either a list of practice IDs or a date "
                "parameter, e.g. date=2015-04-01",
                status=400,
            )

    # We don't (yet?) have a "proper" code field for STPs so we're using their
    # ONS code
    code_field = "code" if org_type != "stp" else "ons_code"

    if org_type == "practice":
        orgs = Practice.objects.all()
    elif org_type == "ccg":
        orgs = PCT.objects.filter(org_type="CCG")
    elif org_type == "pcn":
        orgs = PCN.objects.all()
    elif org_type == "stp":
        orgs = STP.objects.all()
    elif org_type == "regional_team":
        orgs = RegionalTeam.objects.all()
    else:
        return Response("Error: unrecognised org_type parameter", status=400)

    # Filter and sort
    if org_ids:
        orgs = orgs.filter(**{code_field + "__in": org_ids})
    orgs = orgs.order_by(code_field)

    # For most orgs we just want the code and name but for practices we want
    # the entire object because, for compatibility with the existing API, we
    # return extra data for practices
    if org_type != "practice":
        orgs = orgs.only(code_field, "name")

    data = list(_get_prescribing_entries(codes, orgs, org_type, date=date))

    response = Response(data)
    if request.accepted_renderer.format == "csv":
        filename = "spending-by-{}-{}.csv".format(org_type, "-".join(codes))
        response["content-disposition"] = "attachment; filename={}".format(filename)
    return response


def _get_prescribing_entries(bnf_code_prefixes, orgs, org_type, date=None):
    """
    For each date and organisation, yield a dict giving totals for all
    prescribing matching the supplied BNF code prefixes.

    If a date is supplied then data for just that date is returned, otherwise
    all available dates are returned.
    """
    db = get_db()
    items_matrix, quantity_matrix, actual_cost_matrix = _get_prescribing_for_codes(
        db, bnf_code_prefixes
    )
    # If no data at all was found, return early which results in an empty
    # iterator
    if items_matrix is None:
        return
    # Group together practice level data to the appropriate organisation level
    group_by_org = get_row_grouper(org_type)
    items_matrix = group_by_org.sum(items_matrix)
    quantity_matrix = group_by_org.sum(quantity_matrix)
    actual_cost_matrix = group_by_org.sum(actual_cost_matrix)
    # `group_by_org.offsets` maps each organisation's primary key to its row
    # offset within the matrices. We pair each organisation with its row
    # offset, ignoring those organisations which aren't in the mapping (which
    # implies that they did not prescribe in this period)
    org_offsets = [
        (org, group_by_org.offsets[org.pk])
        for org in orgs
        if org.pk in group_by_org.offsets
    ]
    # Pair each date with its column offset (either all available dates or just
    # the specified one)
    if date:
        try:
            date_offsets = [(date, db.date_offsets[date])]
        except KeyError:
            raise BadDate(date)
    else:
        date_offsets = sorted(db.date_offsets.items())
    # Yield entries for each organisation on each date
    for date, col_offset in date_offsets:
        for org, row_offset in org_offsets:
            index = (row_offset, col_offset)
            items = items_matrix[index]
            # Mimicking the behaviour of the existing API, we don't return
            # entries where there was no prescribing
            if items == 0:
                continue
            entry = {
                "items": items,
                "quantity": quantity_matrix[index],
                "actual_cost": round(actual_cost_matrix[index], 2),
                "date": date,
                "row_id": org.pk,
                "row_name": org.name,
            }
            # Practices get some extra attributes in the existing API
            if org_type == "practice":
                entry["ccg"] = org.ccg_id
                entry["setting"] = org.setting
            yield entry


def _get_prescribing_for_codes(db, bnf_code_prefixes):
    """
    Return items, quantity and actual_cost matrices giving the totals for all
    prescribing which matches any of the supplied BNF code prefixes. If no
    prefixes are supplied then the totals will be over all prescribing for all
    presentations.
    """
    if bnf_code_prefixes:
        where_clause = " OR ".join(["bnf_code LIKE ?"] * len(bnf_code_prefixes))
        params = [code + "%" for code in bnf_code_prefixes]
        sql = """
            SELECT
                matrix_sum(items) AS items,
                matrix_sum(quantity) AS quantity,
                matrix_sum(actual_cost) AS actual_cost
            FROM
                presentation
            WHERE
                {}
            """.format(
            where_clause
        )
    else:
        # As summing over all presentations can be quite slow we use the
        # precalculated results table
        sql = "SELECT items, quantity, actual_cost FROM all_presentations"
        params = []
    items, quantity, actual_cost = db.query_one(sql, params)
    # Convert from pence to pounds
    if actual_cost is not None:
        actual_cost = actual_cost / 100.0
    return items, quantity, actual_cost
