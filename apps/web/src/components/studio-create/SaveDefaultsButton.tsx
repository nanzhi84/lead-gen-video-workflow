import { Check, Loader2, Save } from "lucide-react";

type Props = {
  isSaving: boolean;
  justSaved: boolean;
  onSave: () => void;
};

/**
 * "Save as my defaults" action. Persists the current Studio form's preference
 * blocks (not the script/title content) to the server so the next session
 * hydrates from them.
 */
export function SaveDefaultsButton({ isSaving, justSaved, onSave }: Props) {
  return (
    <button
      className="btn-secondary text-sm"
      type="button"
      disabled={isSaving}
      onClick={onSave}
      title="把当前配置存为我的默认，下次进入工作台自动套用"
    >
      {isSaving ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : justSaved ? (
        <Check className="h-4 w-4 text-status-success" />
      ) : (
        <Save className="h-4 w-4" />
      )}
      <span>{justSaved ? "已保存为默认" : "保存为我的默认"}</span>
    </button>
  );
}
