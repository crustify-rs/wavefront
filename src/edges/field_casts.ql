/**
 * Slot edges whose every slot end is a struct FIELD: `type -> field`
 * (a write of a named type into the field), `field -> type` (a read
 * converted to a named type) and `field -> field` (a read stored unchanged
 * into another field). Field <-> function edges are in `edges/arg_casts.ql`;
 * the two tables partition `slotEdge`.
 *
 * See `slots.qll` for the edge kinds, the endpoint encoding and the
 * syntactic-only rule (no dataflow: an edge is missed, never invented).
 * The composer joins `from` -> `forward`* -> `to` into slot-mediated
 * `casted` pairs.
 *
 * # cols:
 *   rel        : "from" | "to" | "forward"
 *   src_kind   : "type" | "param" | "ret" | "field"
 *   src_name   : struct tag, function name, or field owner tag
 *   src_file   : definition file of that entity ("" if only declared)
 *   src_member : "" (type) | parameter position | "ret" | field name
 *   src_decl   : named struct the slot is declared to hold, "" if erased
 *   src_ctype  : declared C type of the slot ("" for a type end)
 *   dst_*      : the same, for the destination end
 *   site_fn    : function the edge is written in ("" at file scope)
 *   site_file  : its definition file (the source file at file scope)
 *   line       : 1-indexed line of the slot access
 */
import cpp
import identity
import slots

from string rel,
     string sk, string sn, string sf, string sm, string sd, string sc,
     string dk, string dn, string df, string dm, string dd, string dc,
     Expr at, string site_fn, string site_file, int line
where
  slotEdge(rel, sk, sn, sf, sm, sd, sc, dk, dn, df, dm, dd, dc, at) and
  not sk = ["param", "ret"] and not dk = ["param", "ret"] and
  siteOf(at, site_fn, site_file, line)
select rel, sk as src_kind, sn as src_name, sf as src_file, sm as src_member,
       sd as src_decl, sc as src_ctype,
       dk as dst_kind, dn as dst_name, df as dst_file, dm as dst_member,
       dd as dst_decl, dc as dst_ctype,
       site_fn, site_file, line
