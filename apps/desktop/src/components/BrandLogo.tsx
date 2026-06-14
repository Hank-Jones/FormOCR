import logoUrl from "../assets/brand/logo.png";

type BrandLogoProps = {
  className?: string;
  alt?: string;
};

export default function BrandLogo({ className = "brand-logo", alt = "FormOCR" }: BrandLogoProps) {
  return <img src={logoUrl} alt={alt} className={className} draggable={false} />;
}
