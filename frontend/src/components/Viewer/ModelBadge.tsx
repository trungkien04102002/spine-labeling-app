/** The letter that tells clinicians which model a panel belongs to. */
export default function ModelBadge({ model }: { model: "A" | "B" }) {
  return (
    <span
      className={
        "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-extrabold text-white " +
        (model === "A" ? "bg-teal-600" : "bg-violet-600")
      }
      aria-hidden
    >
      {model}
    </span>
  );
}
