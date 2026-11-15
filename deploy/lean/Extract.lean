/-
Metis declaration export: the "by script" half of the base graph (overview, Base graph).
Run only inside the pinned mathlib project prepared by scripts/setup_lean.py:

  lake env lean --run /workspace/deploy/lean/Extract.lean OUT.jsonl Mathlib.LinearAlgebra [PREFIX ...]

One JSON object per line: name, kind, module, line, type (pretty printed, every hypothesis kept),
docstring, fields (for structures), dependencies (exported constants used by the type and the
proof/value). No model is involved. Nothing here is a proof audit of anything.

Not exported, because they are plumbing rather than mathematics: instances, structure projection
functions, deprecated aliases, recursors and other compiler-generated declarations.
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

/-- Names Lean generates mechanically. `eq_1`, `eq_def` are equation lemmas; a lemma that is
merely *named* `eq_zero_of_…` is mathematics and is kept. -/
def generatedName (env : Environment) (n : Name) : Bool :=
  match n with
  | .str p s =>
      s.startsWith "proof_" || s.startsWith "match_" || s == "eq_def" || s == "eq_unfold"
      || (s.startsWith "eq_" && s.length > 3 && (s.drop 3).all Char.isDigit)
      || s == "injEq" || s == "sizeOf_spec" || s.endsWith "_sunfold" || s == "below" || s == "ibelow"
      || (s.startsWith "inst" && s.length > 4 && (s.get ⟨4⟩).isUpper)
      || (s == "inj" && (match env.find? p with | some (.ctorInfo _) => true | _ => false))
  | _ => true

def wanted (env : Environment) (n : Name) : Bool :=
  !n.isInternal && !n.isInternalDetail && !(isAuxRecursor env n) && !(isNoConfusion env n)
    && !((instanceExtension.getState env).instanceNames.contains n)
    && !(env.isProjectionFn n) && !(Linter.isDeprecated env n) && !(generatedName env n)

def emit (h : IO.FS.Handle) (env : Environment) (exported : NameSet)
    (n : Name) (ci : ConstantInfo) (module kind : String) : MetaM Unit := do
  let fmt ← withOptions (fun o => (o.setBool `pp.proofs false).setNat `pp.maxSteps 5000) do
    ppExpr ci.type
  let doc ← findDocString? env n
  let ranges ← findDeclarationRanges? n
  let line : Json := match ranges with
    | some r => Json.num r.range.pos.line
    | none => Json.null
  let used := ci.type.getUsedConstants ++ (ci.value?.map Expr.getUsedConstants |>.getD #[])
  let deps := (used.foldl (fun (acc : NameSet) c => if c != n && exported.contains c then acc.insert c else acc) {}).toList
  let fields : Array Name := if isStructure env n then getStructureFields env n else #[]
  let obj := Json.mkObj [
    ("name", Json.str n.toString), ("kind", Json.str kind), ("module", Json.str module),
    ("line", line), ("type", Json.str (fmt.pretty 100)),
    ("docstring", match doc with | some t => Json.str t | none => Json.null),
    ("fields", Json.arr (fields.map fun f => Json.str f.toString)),
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
  let (candidates, exported) := env.constants.fold
    (init := ((#[] : Array (Name × ConstantInfo × String × String)), ({} : NameSet)))
    fun (acc, set) n ci =>
      match moduleOf n, kindOf env n ci with
      | some module, some kind =>
          if wanted env n then (acc.push (n, ci, module, kind), set.insert n) else (acc, set)
      | _, _ => (acc, set)
  IO.eprintln s!"[extract] candidates: {candidates.size}"
  let h ← IO.FS.Handle.mk out IO.FS.Mode.write
  let ctx : Core.Context := { fileName := "<metis-extract>", fileMap := default, maxHeartbeats := 0 }
  let act : MetaM Unit := do
    let mut count := 0
    for (n, ci, module, kind) in candidates do
      try
        emit h env exported n ci module kind
        count := count + 1
        if count % 20000 == 0 then IO.eprintln s!"[extract] {count} of {candidates.size}"
      catch e =>
        IO.eprintln s!"[extract] skipped {n}: {← e.toMessageData.toString}"
    IO.eprintln s!"[extract] written: {count}"
  let _ ← act.toIO ctx { env := env }
  h.flush
