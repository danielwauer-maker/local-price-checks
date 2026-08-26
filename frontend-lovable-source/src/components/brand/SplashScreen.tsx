import { SparenoMark } from "@/components/brand/SparenoLogo";

type SplashScreenProps = {
  exiting?: boolean;
};

export function SplashScreen({ exiting = false }: SplashScreenProps) {
  return (
    <div
      className={`spareno-splash${exiting ? " spareno-splash--exiting" : ""}`}
      role="status"
      aria-label="Spareno wird geladen"
    >
      <div className="spareno-splash__rings" aria-hidden="true" />

      <div className="spareno-splash__brand">
        <SparenoMark className="spareno-splash__mark" />
        <div className="spareno-splash__wordmark" aria-label="Spareno">
          <span>spar</span>
          <span>eno</span>
        </div>
        <p>Clever sparen. Direkt in deiner Nähe</p>
      </div>

      <svg
        className="spareno-splash__waves"
        viewBox="0 0 1440 420"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path
          className="spareno-splash__wave spareno-splash__wave--back"
          d="M0 108C260 142 392 288 640 288c280 0 404-190 800-166v298H0Z"
        />
        <path
          className="spareno-splash__wave spareno-splash__wave--middle"
          d="M0 176c288 138 470 154 674 80 246-90 410-108 766 26v138H0Z"
        />
        <path
          className="spareno-splash__wave spareno-splash__wave--front"
          d="M0 270c256 54 442 32 638-34 300-100 502 68 802 18v166H0Z"
        />
      </svg>
    </div>
  );
}
