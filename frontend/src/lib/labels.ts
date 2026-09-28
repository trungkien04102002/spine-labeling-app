import { anatomyName } from "./clinicalTerms";
import { useT } from "./i18n";

/**
 * Prettify a TotalSpineSeg label name, e.g. "vertebrae_L1" -> "Vertebra L1".
 *
 * Lives here rather than next to the legend because the legend and the brush's
 * label picker must name the same structure identically -- two spellings of
 * "spinal_cord" / "Spinal cord" is what made the picker hard to use.
 */
export function prettyName(name: string): string {
  if (name.startsWith("vertebrae_")) return `Vertebra ${name.slice(10)}`;
  if (name.startsWith("disc_")) return `Disc ${name.slice(5).replace(/_/g, "-")}`;
  return name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** CSS color for a legend/picker swatch, from the labelmap's rendered RGB. */
export function swatchColor(color: [number, number, number]): string {
  return `rgb(${color[0]},${color[1]},${color[2]})`;
}

/**
 * The structure's name in the reader's language. Every place that names a
 * structure goes through this, for the reason prettyName exists at all: the
 * legend and the brush picker must call a structure the same thing.
 */
export function useStructureName(): (raw: string) => string {
  const { lang } = useT();
  return (raw: string) => anatomyName(raw, prettyName(raw), lang);
}
