type RateLimitNoticeProps = {
  cooldownSeconds: number;
};

export default function RateLimitNotice({ cooldownSeconds }: RateLimitNoticeProps) {
  return (
    <div data-testid="rate-limit-notice" className="mx-4 mb-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
      You&apos;re sending messages too quickly. Please wait {cooldownSeconds}s before trying again.
    </div>
  );
}
