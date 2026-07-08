// Renders clarification options: splits `assistant_message` on `\n` and treats
// lines matching `^[-*]\s` or `^\d+\.\s` as individual option strings — no
// interpretation of option content beyond stripping the leading marker.
const OPTION_LINE_PATTERN = /^([-*]|\d+\.)\s/;
const OPTION_MARKER_PATTERN = /^[-*\d.]+\s/;

type ClarificationOptionsProps = {
  message: string;
  onSelect: (text: string) => void;
};

export default function ClarificationOptions({ message, onSelect }: ClarificationOptionsProps) {
  const lines = message.split("\n");
  const optionLines = lines.filter((line) => OPTION_LINE_PATTERN.test(line.trim()));
  const introText = lines
    .filter((line) => !OPTION_LINE_PATTERN.test(line.trim()))
    .join("\n")
    .trim();

  return (
    <div className="flex flex-col gap-2 rounded-lg bg-gray-100 px-4 py-3 text-sm text-gray-900">
      {introText && <p>{introText}</p>}
      <div className="flex flex-wrap gap-2">
        {optionLines.map((line, index) => {
          const optionText = line.trim().replace(OPTION_MARKER_PATTERN, "").trim();
          return (
            <button
              key={index}
              type="button"
              data-testid="clarification-option"
              onClick={() => onSelect(optionText)}
              className="rounded-full border border-blue-500 px-3 py-1 text-blue-600 hover:bg-blue-50"
            >
              {optionText}
            </button>
          );
        })}
      </div>
    </div>
  );
}
