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
    <div className="flex animate-message-in flex-col gap-2 rounded-2xl rounded-bl-sm border border-slate-100 bg-white px-4 py-3 text-sm text-slate-800 shadow-sm">
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
              className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-blue-700 transition-colors hover:border-blue-400 hover:bg-blue-100"
            >
              {optionText}
            </button>
          );
        })}
      </div>
    </div>
  );
}
