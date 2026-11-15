/-
Metis declaration export: the "by script" half of the base graph (overview, Base graph).
Run only inside the pinned mathlib project prepared by scripts/setup_lean.py:

  lake env lean --run /workspace/deploy/lean/Extract.lean OUT.jsonl Mathlib.LinearAlgebra [PREFIX ...]

One JSON object per line: name, kind, module, line, type (pretty printed, every hypothesis kept),
docstring, dependencies (constants used by the type and the proof/value, restricted to the
exported prefixes). No model is involved. Nothing here is a proof audit of anything.
-/
import Mathlib
open Lean Meta

def underPrefix (prefixes : List String) (module : String) : Bool :=
  prefixes.any fun p => module == p || module.startsWith (p ++ ".")

def kindOf (env : Environment) (n : Name) (ci : ConstantInfo) : Option String :=
  match ci with
  | .thmInfo _ => some "theorem"
  | .axiomInfo _ => some "axiom"
  | .opaqueInfo _ => some "opaque"
  | .defnInfo _ => some "def"
  | .inductInfo _ =>
      if isStructure env n then some (if isClass env n then "class" else "structure")
      else some "inductive"
  | _ => none

def wanted (env : Environment) (n : Name) : Bool :=
  !n.isInternal && !n.isInternalDetail && !(isAuxRecursor env n) && !(isNoConfusion env n)
    && !((instanceExtension.getState env).instanceNames.contains n)
    && !(n.getString!.startsWith "inst")
    && !(n.getString!.startsWith "proof_") && !(n.getString!.startsWith "match_")
    && !(n.getString!.startsWith "eq_") && !(n.getString!.startsWith "injEq")
    && !(n.getString!.startsWith "sizeOf_spec") && !(n.getString!.endsWith "_sunfold")

def escapeOpt (s : Option String) : Json :=
  match s with | some t => Json.str t | none => Json.null

def emit (h : IO.FS.Handle) (env : Environment)
    (n : Name) (ci : ConstantInfo) (moduleOf : Name → Option String) : MetaM Unit := do
  let some module := moduleOf n | return
  let some kind := kindOf env n ci | return
  let fmt ← withOptions (fun o => (o.setBool `pp.proofs false).setNat `pp.maxSteps 5000) do
    ppExpr ci.type
  let doc ← findDocString? env n
  let ranges ← findDeclarationRanges? n
  let line : Json := match ranges with
    | some r => Json.num r.range.pos.line
    | none => Json.null
  let used := ci.type.getUsedConstants ++ (ci.value?.map Expr.getUsedConstants |>.getD #[])
  let deps := (used.foldl (fun (acc : NameSet) c => acc.insert c) {}).toList.filter fun c =>
    c != n && wanted env c && (moduleOf c).isSome
  let obj := Json.mkObj [
    ("name", Json.str n.toString), ("kind", Json.str kind), ("module", Json.str module),
    ("line", line), ("type", Json.str (fmt.pretty 100)), ("docstring", escapeOpt doc),
    ("dependencies", Json.arr (deps.toArray.map fun c => Json.str c.toString)) ]
  h.putStrLn obj.compress

def main (args : List String) : IO Unit := do
  let out :: prefixes := args | throw <| IO.userError "usage: Extract OUT.jsonl PREFIX [PREFIX ...]"
  initSearchPath (← findSysroot)
  let env ← importModules #[{ module := `Mathlib }] {} (trustLevel := 0) (loadExts := true)
  let names := env.header.moduleNames
  let moduleOf (n : Name) : Option String :=
    match env.getModuleIdxFor? n with
    | some idx =>
        let m := names[idx.toNat]!.toString
        if underPrefix prefixes m then some m else none
    | none => none
  let candidates := env.constants.fold (init := ([] : List (Name × ConstantInfo))) fun acc n ci =>
    if wanted env n && (moduleOf n).isSome then (n, ci) :: acc else acc
  IO.eprintln s!"[extract] candidates: {candidates.length}"
  let h ← IO.FS.Handle.mk out IO.FS.Mode.write
  let ctx : Core.Context := { fileName := "<metis-extract>", fileMap := default, maxHeartbeats := 0 }
  let act : MetaM Unit := do
    let mut count := 0
    for (n, ci) in candidates do
      try
        emit h env n ci moduleOf
        count := count + 1
      catch e =>
        IO.eprintln s!"[extract] skipped {n}: {← e.toMessageData.toString}"
    IO.eprintln s!"[extract] written: {count}"
  let _ ← act.toIO ctx { env := env }
  h.flush
